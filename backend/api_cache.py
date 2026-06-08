"""Cache kết quả API đọc nặng từ DB — filter options, v.v."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_filter_opts_cache: tuple[float, tuple[int, str | None], dict[str, list[str]]] | None = None
FILTER_OPTS_TTL = 600


def get_tour_filter_options(db: Session) -> dict[str, list[str]]:
    """Distinct cột filter — cache 10 phút, invalidate khi tour đổi."""
    from compare_cache import _db_fingerprint
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    global _filter_opts_cache
    fp = _db_fingerprint(db)
    now = time.time()
    with _lock:
        hit = _filter_opts_cache
        if hit and now - hit[0] < FILTER_OPTS_TTL and hit[1] == fp:
            return hit[2]

    from tour_filters import EXCLUDED_MARKETS, market_filter_clause

    def distinct(col):
        q = db.query(col).filter(col != "")
        # Loại trừ "Không xác định" khỏi list thi_truong (col is Tour.thi_truong)
        if col is Tour.thi_truong:
            q = q.filter(market_filter_clause(Tour))
        return [r[0] for r in q.distinct().order_by(col).all() if r[0] not in EXCLUDED_MARKETS]

    pairs = (
        db.query(Tour.thi_truong, Tour.tuyen_tour)
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.thi_truong != "", Tour.tuyen_tour != "")
        .filter(market_filter_clause(Tour))
        .distinct()
        .order_by(Tour.thi_truong, Tour.tuyen_tour)
        .all()
    )
    routes_by_market: dict[str, list[str]] = {}
    for mk, rt in pairs:
        if mk and rt:
            routes_by_market.setdefault(mk, []).append(rt)

    data = {
        "thi_truong": distinct(Tour.thi_truong),
        "tuyen_tour": distinct(Tour.tuyen_tour),
        "routes_by_market": routes_by_market,
        "cong_ty": distinct(Tour.cong_ty),
        "diem_kh": distinct(Tour.diem_kh),
        "nguon": [n for n in distinct(Tour.nguon) if n in DB_CANONICAL_NGUON],
        "phan_khuc": distinct(Tour.phan_khuc),
    }
    with _lock:
        _filter_opts_cache = (now, fp, data)
    logger.info("Built tour filter-options cache (%s markets)", len(data["thi_truong"]))
    return data


def invalidate_api_read_cache() -> None:
    global _filter_opts_cache
    with _lock:
        _filter_opts_cache = None
