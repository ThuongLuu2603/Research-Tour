"""Phát hiện tuyến / thị trường không nhất quán trong dữ liệu Sheet."""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Tour

logger = logging.getLogger(__name__)

_hist_lock = threading.Lock()
_hist_cache: tuple[float, tuple[int, str | None], dict[str, list[tuple[str, int]]]] | None = None
HIST_TTL = 600


def load_tuyen_market_histogram(db: Session) -> dict[str, list[tuple[str, int]]]:
    rows = (
        db.query(Tour.tuyen_tour, Tour.thi_truong, func.count(Tour.id))
        .filter(Tour.gia != None, Tour.tuyen_tour != "")  # noqa: E711
        .group_by(Tour.tuyen_tour, Tour.thi_truong)
        .all()
    )
    hist: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for tuyen, market, cnt in rows:
        tuyen = (tuyen or "").strip()
        market = (market or "").strip()
        if tuyen:
            hist[tuyen].append((market, int(cnt)))
    return hist


def load_tuyen_market_histogram_cached(db: Session) -> dict[str, list[tuple[str, int]]]:
    """GROUP BY tuyến×TT — cache 10 phút (Market Lab gọi mỗi lần mở trang)."""
    from compare_cache import _db_fingerprint

    global _hist_cache
    fp = _db_fingerprint(db)
    now = time.time()
    with _hist_lock:
        hit = _hist_cache
        if hit and now - hit[0] < HIST_TTL and hit[1] == fp:
            return hit[2]

    t0 = time.time()
    hist = load_tuyen_market_histogram(db)
    with _hist_lock:
        _hist_cache = (now, fp, hist)
    logger.info("Built tuyen×market histogram (%s routes) in %.1fs", len(hist), time.time() - t0)
    return hist


def invalidate_route_quality_cache() -> None:
    global _hist_cache
    with _hist_lock:
        _hist_cache = None


def assess_route_quality(
    thi_truong: str,
    tuyen_tour: str,
    hist: dict[str, list[tuple[str, int]]],
) -> dict:
    market = (thi_truong or "").strip()
    route = (tuyen_tour or "").strip()
    if not route:
        return {"quality": "ok", "quality_note": ""}

    if route.casefold() == market.casefold():
        return {
            "quality": "generic",
            "quality_note": "Tuyến trùng tên thị trường — phần lớn tour chưa gán tuyến chi tiết (chỉ có cột Thị trường).",
        }

    entries = hist.get(route, [])
    if not entries:
        return {"quality": "ok", "quality_note": ""}

    total = sum(c for _, c in entries)
    dominant_mk, dom_cnt = max(entries, key=lambda x: x[1])
    share = dom_cnt / max(total, 1)

    if dominant_mk != market and share >= 0.45:
        return {
            "quality": "market_mismatch",
            "quality_note": (
                f"~{round(share * 100)}% tour có Tuyến tour «{route}» được gán Thị trường «{dominant_mk}», "
                f"không phải «{market}» — cần sửa phân loại trên Sheet."
            ),
            "dominant_market": dominant_mk,
        }

    return {"quality": "ok", "quality_note": ""}
