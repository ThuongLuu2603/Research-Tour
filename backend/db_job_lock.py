"""Database-level locks for long jobs that write shared tables."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text

from config import settings

logger = logging.getLogger(__name__)

TOURS_WRITE_LOCK = (874260, 1)


def _is_postgres() -> bool:
    url = settings.database_url
    return url.startswith("postgresql") or url.startswith("cockroachdb")


def _is_cockroach() -> bool:
    url = settings.database_url
    return "cockroachlabs.cloud" in url or url.startswith("cockroachdb")


def _combined_key(key: tuple[int, int]) -> int:
    """Gộp 2 khoá int32 thành 1 khoá int64 (CockroachDB chỉ hỗ trợ bản 1 tham số bigint)."""
    return (int(key[0]) << 32) | (int(key[1]) & 0xFFFFFFFF)


@contextmanager
def advisory_lock(db, key: tuple[int, int], owner: str) -> Iterator[bool]:
    """Take a session-level advisory lock that holds for the WHOLE job.

    QUAN TRỌNG: advisory lock của Postgres/CockroachDB gắn với *connection*. Engine dùng
    NullPool, nên mỗi ``db.commit()`` của job (commit theo batch) sẽ trả connection về pool →
    NullPool đóng connection → lock bị tự nhả. Vì vậy lock PHẢI nằm trên một connection riêng
    được giữ mở suốt job, KHÔNG dùng chung session ``db`` đang ghi dữ liệu.

    - Postgres/Supabase: pg_try_advisory_lock(int, int) (2 tham số).
    - CockroachDB: chỉ hỗ trợ bản 1 tham số bigint → gộp 2 khoá thành 1.
    - DB không hỗ trợ / lỗi mở connection: degrade an toàn (chạy tiếp không khoá) thay vì
      để job báo lỗi cho người dùng.

    ``db`` được giữ trong chữ ký để tương thích caller nhưng không dùng cho việc khoá.
    """
    if not _is_postgres():
        yield True
        return

    from database import engine

    use_single = _is_cockroach()
    conn = None
    got = False
    try:
        # AUTOCOMMIT: không giữ transaction mở lâu (tránh CockroachDB hủy txn idle làm rớt lock).
        conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        if use_single:
            scalar = conn.execute(
                text("select pg_try_advisory_lock(:k)"), {"k": _combined_key(key)}
            ).scalar()
        else:
            scalar = conn.execute(
                text("select pg_try_advisory_lock(:k1, :k2)"),
                {"k1": int(key[0]), "k2": int(key[1])},
            ).scalar()
        got = bool(scalar)
    except Exception as e:
        logger.warning(
            "DB advisory lock không khả dụng owner=%s key=%s: %s — chạy tiếp không khoá",
            owner, key, e,
        )
        _safe_close(conn)
        yield True
        return

    if not got:
        logger.warning("DB advisory lock busy: owner=%s key=%s", owner, key)
        _safe_close(conn)
        yield False
        return

    try:
        yield True
    finally:
        try:
            if use_single:
                conn.execute(text("select pg_advisory_unlock(:k)"), {"k": _combined_key(key)})
            else:
                conn.execute(
                    text("select pg_advisory_unlock(:k1, :k2)"),
                    {"k1": int(key[0]), "k2": int(key[1])},
                )
        except Exception as e:
            logger.warning("DB advisory unlock failed owner=%s key=%s: %s", owner, key, e)
        finally:
            _safe_close(conn)


def _safe_close(conn) -> None:
    if conn is not None:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def tours_write_lock(db, owner: str) -> Iterator[bool]:
    with advisory_lock(db, TOURS_WRITE_LOCK, owner) as locked:
        yield locked
