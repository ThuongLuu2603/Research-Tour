"""Retry cho lỗi TẠM THỜI của CockroachDB (Serverless hay gặp khi node/heartbeat chập chờn).

CockroachDB có thể ném các lỗi không phải do dữ liệu sai mà do hạ tầng:
- StatementCompletionUnknown / "result is ambiguous" (commit không chắc thành công)
- "conn heartbeat timed out" / "context deadline exceeded" (gRPC giữa các node)
- Serialization 40001 / "restart transaction" (cần thử lại transaction)

Những lỗi này nên RETRY (idempotent upsert → chạy lại an toàn) thay vì báo lỗi cho người dùng.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar

from sqlalchemy.exc import DatabaseError, DBAPIError, OperationalError

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Mã lỗi pgcode coi là tạm thời (thử lại được).
_TRANSIENT_PGCODES = {"40001", "40003", "40P01", "08006", "08003", "57P01", "XX000"}

# Chuỗi trong message coi là tạm thời.
_TRANSIENT_SUBSTRINGS = (
    "statementcompletionunknown",
    "result is ambiguous",
    "ambiguous",
    "conn heartbeat",
    "heartbeat",
    "deadline exceeded",
    "restart transaction",
    "connection reset",
    "connection refused",
    "server closed the connection",
    "could not connect",
    "failed to send rpc",
    "context deadline",
)


def is_transient_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(s in msg for s in _TRANSIENT_SUBSTRINGS):
        return True
    orig = getattr(exc, "orig", None)
    code = getattr(orig, "pgcode", None)
    if code and code in _TRANSIENT_PGCODES:
        return True
    return False


def run_with_retry(
    fn: Callable[[], T],
    *,
    db=None,
    max_attempts: int = 3,
    base_wait: float = 0.5,
    label: str = "db-op",
) -> T:
    """Chạy ``fn`` và thử lại nếu gặp lỗi tạm thời. Rollback ``db`` (nếu có) trước mỗi lần thử lại."""
    last: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except (DBAPIError, DatabaseError, OperationalError) as e:
            if not is_transient_error(e):
                raise
            last = e
            if db is not None:
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            if attempt < max_attempts - 1:
                wait = base_wait * (2 ** attempt)
                logger.warning(
                    "%s: lỗi tạm thời (%s), thử lại %d/%d sau %.1fs",
                    label, type(e).__name__, attempt + 1, max_attempts, wait,
                )
                time.sleep(wait)
    assert last is not None
    logger.error("%s: hết lượt thử lại sau %d lần", label, max_attempts)
    raise last
