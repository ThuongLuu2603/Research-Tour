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
    from sqlalchemy.orm import load_only
    from data_sources import DB_CANONICAL_NGUON

    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    tours = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        .all()
    )
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


def recompute_phan_khuc_for_tour_ids(db: Session, tour_ids: list[int]) -> dict:
    """Tính lại phân khúc cho danh sách tour (vd. sau scrape chỉ tour mới/cập nhật)."""
    from data_sources import DB_CANONICAL_NGUON

    ids = [int(i) for i in tour_ids if i]
    if not ids:
        return {"updated": 0, "tours": 0}

    from sqlalchemy.orm import load_only
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(all_priced)
    tours = db.query(Tour).options(load_only(*_PRICE_COLS)).filter(Tour.id.in_(ids)).all()
    updated = 0
    for t in tours:
        label = phan_khuc_relative_for_tour(t, route_avg)
        if t.phan_khuc != label:
            t.phan_khuc = label[:64]
            updated += 1
    if updated:
        db.commit()
    return {"updated": updated, "tours": len(tours), "route_buckets": len(route_avg)}


def recompute_segments_for_sync(db: Session, affected_tour_ids: set[int] | list[int]) -> dict:
    """Phân khúc cho tour mới (thiếu nhãn) + tour vừa thay đổi — không quét toàn DB."""
    missing = recompute_missing_phan_khuc(db)
    targeted = recompute_phan_khuc_for_tour_ids(db, list(affected_tour_ids))
    return {
        "missing_filled": missing,
        "targeted_updated": targeted.get("updated", 0),
        "targeted_tours": targeted.get("tours", 0),
        "route_buckets": targeted.get("route_buckets", 0),
    }


def recompute_missing_phan_khuc(db: Session) -> int:
    """Tính phân khúc cho tour có giá nhưng chưa có nhãn (vd. Vietravel mới scrape)."""
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour
    from sqlalchemy import or_

    from sqlalchemy.orm import load_only
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    tours = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        .filter(or_(Tour.phan_khuc.is_(None), Tour.phan_khuc == "", Tour.phan_khuc == "Chưa có giá"))
        .all()
    )
    if not tours:
        return 0
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(all_priced)
    updated = 0
    for t in tours:
        label = phan_khuc_relative_for_tour(t, route_avg)
        if label and t.phan_khuc != label:
            t.phan_khuc = label[:64]
            updated += 1
    if updated:
        db.commit()
    return updated
