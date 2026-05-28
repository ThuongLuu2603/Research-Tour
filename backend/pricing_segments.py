"""Phân khúc giá theo TB/ngày tour so với TB/ngày TT trên cùng Thị trường + Tuyến + Điểm KH."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from models import Tour

# Ngưỡng so với TB/ngày thị trường (cùng nhóm segment)
LUXURY_ABOVE_MARKET = 1.30
STANDARD_BELOW_MARKET = 0.70


def bucket_key_for_tour(t: Tour) -> str | None:
    """Cùng khóa nhóm với So sánh VTR: Thị trường | Tuyến | Điểm khởi hành."""
    from compare_engine import make_segment_key, normalize_departure, route_for_segment

    route = route_for_segment(t)
    if not route:
        return None
    market = (t.thi_truong or "").strip() or "Khác"
    depart = normalize_departure(t.diem_kh)
    return make_segment_key(market, route, depart)


def tour_price_per_day(gia: float | None, thoi_gian: str, so_ngay: float | None) -> float | None:
    from classification import resolve_duration_days

    days, _ = resolve_duration_days(thoi_gian or "", so_ngay)
    if not gia or not days or days <= 0:
        return None
    pd = float(gia) / float(days)
    if pd <= 0 or pd > 50_000_000:
        return None
    return pd


def build_route_market_avg_price_day(tours: list[Tour]) -> dict[str, float]:
    """TB/ngày TT = TB giá/ngày tour đối thủ (không tab Vietravel) trong cùng segment."""
    from tour_sources import is_vietravel_tab

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in tours:
        if is_vietravel_tab(t):
            continue
        pd = tour_price_per_day(t.gia, t.thoi_gian, t.so_ngay)
        if pd is None:
            continue
        key = bucket_key_for_tour(t)
        if not key:
            continue
        sums[key] += pd
        counts[key] += 1
    return {k: round(sums[k] / counts[k], 0) for k in sums if counts[k] > 0}


def phan_khuc_relative_for_tour(t: Tour, route_avg: dict[str, float]) -> str:
    pd = tour_price_per_day(t.gia, t.thoi_gian, t.so_ngay)
    if pd is None:
        return "Chưa có giá"
    key = bucket_key_for_tour(t)
    mkt = route_avg.get(key) if key else None
    if not mkt:
        return _phan_khuc_absolute_fallback(t.gia)
    ratio = pd / mkt
    if ratio >= LUXURY_ABOVE_MARKET:
        return "Luxury"
    if ratio <= STANDARD_BELOW_MARKET:
        return "Standard"
    return "Premium"


def _phan_khuc_absolute_fallback(gia: float | None) -> str:
    if not gia:
        return "Chưa có giá"
    if gia < 2_000_000:
        return "Standard"
    if gia < 5_000_000:
        return "Standard"
    if gia < 15_000_000:
        return "Premium"
    return "Luxury"


def recompute_all_phan_khuc(db: Session) -> dict:
    tours = db.query(Tour).all()
    route_avg = build_route_market_avg_price_day(tours)
    updated = 0
    for t in tours:
        label = phan_khuc_relative_for_tour(t, route_avg)
        if t.phan_khuc != label:
            t.phan_khuc = label[:64]
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "route_buckets": len(route_avg)}
