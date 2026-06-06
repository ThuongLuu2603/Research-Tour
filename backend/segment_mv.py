"""Materialized view thống kê segment — ĐÃ BỎ.

Trước đây MV `mv_tour_segment_stats` được REFRESH sau mỗi sync nhưng KHÔNG hề được SELECT ở đâu
(So sánh dùng cache in-memory). Trên CockroachDB, `REFRESH MATERIALIZED VIEW [CONCURRENTLY]` treo
rất lâu + đẻ rác MVCC GC chất đống → làm job "Đang commit & phân khúc giá" bị kẹt. Vì vô dụng nên
ta vô hiệu hoá refresh và DROP MV cùng index để dọn sạch.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from database import engine
from tour_search import is_postgres

logger = logging.getLogger(__name__)

MV_NAME = "mv_tour_segment_stats"


def ensure_materialized_view() -> None:
    """No-op — không tạo lại MV nữa."""
    return None


def refresh_segment_mv(*, concurrent: bool = True) -> bool:
    """No-op — không refresh MV nữa (tránh treo job + tốn RU/GC trên CockroachDB)."""
    return False


def drop_materialized_view() -> None:
    """Xóa MV + index cũ (dọn các job REFRESH/GC đang kẹt). Idempotent, best-effort."""
    if not is_postgres():
        return
    for stmt in (
        f"DROP MATERIALIZED VIEW IF EXISTS {MV_NAME} CASCADE",
        f"DROP INDEX IF EXISTS idx_{MV_NAME}_key",
    ):
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception as e:  # noqa: BLE001
            logger.warning("drop_materialized_view (%s): %s", stmt, e)
