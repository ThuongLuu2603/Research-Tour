"""Khóa cấp DB cho job ghi bảng Tour — dùng lease lock (bảng job_lock).

Lý do KHÔNG dùng pg_try_advisory_lock: CockroachDB không hỗ trợ thật (hàm trả về true kiểu no-op
hoặc lỗi → degrade thành không khóa), nên 2 job ghi Tour cùng lúc → lỗi 40001 SerializationFailure
và tranh chấp làm job chậm/treo. Lease lock là 1 DÒNG dữ liệu (job_lock) với UPSERT có điều kiện
expires_at < now() — nguyên tử, xuyên process/instance, sống sót qua các commit theo batch, và tự
hết hạn nếu job chết (chống treo).
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from config import settings

logger = logging.getLogger(__name__)

TOURS_WRITE_LOCK_NAME = "tours_write"
_LEASE_TTL_SEC = 300           # khóa hết hạn sau 5 phút nếu không gia hạn
_HEARTBEAT_SEC = 60            # gia hạn mỗi 60s → chịu được ~5 lần renew lỗi liên tiếp trước khi hết hạn

# UPSERT nguyên tử: giành/đoạt-lại khóa nếu chưa có hoặc đã hết hạn. RETURNING rỗng = đang bận.
_ACQUIRE_SQL = text(
    """
    INSERT INTO job_lock (name, holder, expires_at)
    VALUES (:name, :holder, now() + (:ttl * INTERVAL '1 second'))
    ON CONFLICT (name) DO UPDATE
      SET holder = excluded.holder, expires_at = excluded.expires_at
      WHERE job_lock.expires_at < now()
    RETURNING holder
    """
)
_RENEW_SQL = text(
    "UPDATE job_lock SET expires_at = now() + (:ttl * INTERVAL '1 second') "
    "WHERE name = :name AND holder = :holder"
)
_RELEASE_SQL = text("DELETE FROM job_lock WHERE name = :name AND holder = :holder")


def _is_postgres() -> bool:
    url = settings.database_url
    return url.startswith("postgresql") or url.startswith("cockroachdb")


def _acquire(name: str, holder: str) -> bool:
    from database import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        row = conn.execute(_ACQUIRE_SQL, {"name": name, "holder": holder, "ttl": _LEASE_TTL_SEC}).first()
    return bool(row) and row[0] == holder


def _renew(name: str, holder: str) -> int:
    """Gia hạn lease. Trả về số dòng cập nhật — 0 nghĩa là đã MẤT lease (bị job khác đoạt)."""
    from database import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        res = conn.execute(_RENEW_SQL, {"name": name, "holder": holder, "ttl": _LEASE_TTL_SEC})
        return res.rowcount or 0


def _release(name: str, holder: str) -> None:
    from database import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(_RELEASE_SQL, {"name": name, "holder": holder})


def force_release(name: str = TOURS_WRITE_LOCK_NAME) -> int:
    """Xóa khóa BẤT KỂ holder — dùng khi job bị kill giữa chừng để lại khóa kẹt.
    Trả về số khóa đã xóa."""
    if not _is_postgres():
        return 0
    from database import engine

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        res = conn.execute(text("DELETE FROM job_lock WHERE name = :name"), {"name": name})
        return res.rowcount or 0


@contextmanager
def _heartbeat(name: str, holder: str) -> Iterator[None]:
    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(_HEARTBEAT_SEC):
            # Thử gia hạn, retry 1 lần nhanh nếu lỗi tạm thời (CockroachDB hay chập chờn).
            for attempt in range(2):
                try:
                    rows = _renew(name, holder)
                    if rows == 0:
                        logger.error("job_lock MẤT lease name=%s holder=%s — có thể job khác đã đoạt", name, holder)
                    break
                except Exception as e:  # noqa: BLE001
                    logger.warning("job_lock renew lỗi name=%s (lần %d): %s", name, attempt + 1, e)
                    if attempt == 0 and stop.wait(5):
                        return

    t = threading.Thread(target=_loop, daemon=True, name=f"lock-hb-{name}")
    t.start()
    try:
        yield
    finally:
        stop.set()


@contextmanager
def job_lock(name: str, owner: str) -> Iterator[bool]:
    """Giành lease lock cho ``name``. yield True nếu giữ được khóa, False nếu job khác đang giữ.

    DB không phải Postgres/Cockroach (vd SQLite local): bỏ qua khóa (yield True).
    Lỗi hạ tầng khóa: degrade an toàn (yield True) để không chặn job vì sự cố khóa.
    """
    if not _is_postgres():
        yield True
        return

    holder = uuid.uuid4().hex
    try:
        got = _acquire(name, holder)
    except Exception as e:  # noqa: BLE001
        logger.warning("job_lock acquire lỗi name=%s owner=%s: %s — chạy tiếp không khóa", name, owner, e)
        yield True
        return

    if not got:
        logger.warning("job_lock đang bận name=%s owner=%s", name, owner)
        yield False
        return

    try:
        with _heartbeat(name, holder):
            yield True
    finally:
        try:
            _release(name, holder)
        except Exception as e:  # noqa: BLE001
            logger.warning("job_lock release lỗi name=%s: %s", name, e)


@contextmanager
def tours_write_lock(db, owner: str) -> Iterator[bool]:
    # ``db`` giữ trong chữ ký để tương thích caller; khóa nằm ở bảng job_lock riêng.
    with job_lock(TOURS_WRITE_LOCK_NAME, owner) as locked:
        yield locked
