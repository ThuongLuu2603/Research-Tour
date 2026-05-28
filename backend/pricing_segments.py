"""Phân khúc giá theo TB/ngày tour so với TB/ngày trung bình thị trường trên cùng Thị trường + Tuyến."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from models import Tour

# Ngưỡng so với TB/ngày thị trường (cùng tuyến)
LUXURY_ABOVE_MARKET = 1.30
STANDARD_BELOW_MARKET = 0.70


def _route_key(thi_truong: str, tuyen_tour: str) -> str:
    return f"{(thi_truong or '').strip()}|{(tuyen_tour or '').strip()}"


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
    """TB/ngày thị trường = trung bình giá/ngày các tour đối thủ (không tab Vietravel) trên cùng tuyến."""
    from tour_sources import is_vietravel_tab

    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in tours:
        if is_vietravel_tab(t):
            continue
        pd = tour_price_per_day(t.gia, t.thoi_gian, t.so_ngay)
        if pd is None:
            continue
        key = _route_key(t.thi_truong, t.tuyen_tour)
        if key in ("", "|", "Khác|"):
            continue
        sums[key] += pd
        counts[key] += 1
    return {k: round(sums[k] / counts[k], 0) for k in sums if counts[k] > 0}


def phan_khuc_relative(
    gia: float | None,
    thoi_gian: str,
    so_ngay: float | None,
    thi_truong: str,
    tuyen_tour: str,
    route_avg: dict[str, float],
) -> str:
    pd = tour_price_per_day(gia, thoi_gian, so_ngay)
    if pd is None:
        return "Chưa có giá"
    mkt = route_avg.get(_route_key(thi_truong, tuyen_tour))
    if not mkt:
        return _phan_khuc_absolute_fallback(gia)
    ratio = pd / mkt
    if ratio >= LUXURY_ABOVE_MARKET:
        return "Luxury (>+30% TB/ngày TT)"
    if ratio <= STANDARD_BELOW_MARKET:
        return "Standard (<−30% TB/ngày TT)"
    return "Premium (±30% TB/ngày TT)"


def _phan_khuc_absolute_fallback(gia: float | None) -> str:
    if not gia:
        return "Chưa có giá"
    if gia < 2_000_000:
        return "Budget (<2tr)"
    if gia < 5_000_000:
        return "Mid (2–5tr)"
    if gia < 15_000_000:
        return "Premium (5–15tr)"
    return "Luxury (>15tr)"


def recompute_all_phan_khuc(db: Session) -> dict:
    tours = db.query(Tour).all()
    route_avg = build_route_market_avg_price_day(tours)
    updated = 0
    for t in tours:
        label = phan_khuc_relative(t.gia, t.thoi_gian, t.so_ngay, t.thi_truong, t.tuyen_tour, route_avg)
        if t.phan_khuc != label:
            t.phan_khuc = label[:64]
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "route_buckets": len(route_avg)}
