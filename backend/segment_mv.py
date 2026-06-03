"""Materialized view thống kê segment — PostgreSQL."""
from __future__ import annotations

import logging

from sqlalchemy import text

from database import engine
from tour_search import is_postgres

logger = logging.getLogger(__name__)

MV_NAME = "mv_tour_segment_stats"

_CREATE_SQL = f"""
CREATE MATERIALIZED VIEW IF NOT EXISTS {MV_NAME} AS
SELECT
    COALESCE(NULLIF(trim(thi_truong), ''), 'Khác') AS thi_truong,
    COALESCE(NULLIF(trim(tuyen_tour), ''), '') AS tuyen_tour,
    COALESCE(NULLIF(trim(diem_kh), ''), '') AS diem_kh,
    COUNT(*)::int AS tour_count,
    COUNT(*) FILTER (WHERE gia IS NOT NULL AND gia > 0)::int AS priced_count,
    AVG(gia) FILTER (WHERE gia IS NOT NULL AND gia > 0) AS avg_gia
FROM tours
WHERE nguon IN ('Main', 'Vietravel')
GROUP BY 1, 2, 3
WITH NO DATA
"""

_UNIQUE_IDX = f"""
CREATE UNIQUE INDEX IF NOT EXISTS idx_{MV_NAME}_key
ON {MV_NAME} (thi_truong, tuyen_tour, diem_kh)
"""


def ensure_materialized_view() -> None:
    if not is_postgres():
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(_CREATE_SQL))
            conn.execute(text(_UNIQUE_IDX))
    except Exception as e:
        logger.warning("ensure_materialized_view: %s", e)


def refresh_segment_mv(*, concurrent: bool = True) -> bool:
    if not is_postgres():
        return False
    ensure_materialized_view()
    mode = "CONCURRENTLY" if concurrent else ""
    try:
        with engine.begin() as conn:
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {mode} {MV_NAME}"))
        logger.info("Refreshed %s", MV_NAME)
        return True
    except Exception as e:
        logger.warning("refresh_segment_mv concurrent failed (%s), retry without", e)
        try:
            with engine.begin() as conn:
                conn.execute(text(f"REFRESH MATERIALIZED VIEW {MV_NAME}"))
            return True
        except Exception as e2:
            logger.warning("refresh_segment_mv failed: %s", e2)
            return False
