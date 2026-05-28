"""Phát hiện tuyến / thị trường không nhất quán trong dữ liệu Sheet."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Tour


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
