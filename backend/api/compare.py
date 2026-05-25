from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user
from compare_engine import (
    METHODOLOGY,
    build_competitor_overview,
    build_segment_stats,
    deduplicate_tours,
    is_vietravel,
    segment_key,
)
from config import settings
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/compare", tags=["compare"])


def _load_tours(db: Session, thi_truong: list[str], tuyen_tour: str = "", diem_kh: str = "") -> list[Tour]:
    q = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.ilike(f"%{tuyen_tour}%"))
    if diem_kh:
        q = q.filter(Tour.diem_kh.ilike(f"%{diem_kh}%"))
    return q.all()


class CompareSummary(BaseModel):
    company: str
    total_vietravel_tours: int
    total_market_tours: int
    segments_with_vietravel: int
    cheaper_count: int
    expensive_count: int
    similar_count: int
    avg_gap_pct: float | None
    vtr_freq_monthly_total: float
    vtr_avg_departures_per_month: float | None = None
    market_freq_monthly_total: float
    freq_leading_segments: int
    freq_lagging_segments: int
    methodology: str


@router.get("/summary", response_model=CompareSummary)
def compare_summary(
    thi_truong: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = deduplicate_tours(_load_tours(db, thi_truong))
    segments = build_segment_stats(tours, dedup=False)
    cheaper = expensive = similar = freq_lead = freq_lag = 0
    gaps = []
    vtr_freq = market_freq = 0.0

    for s in segments:
        g = s.gap_pct
        if g is not None:
            gaps.append(g)
            if g <= -5:
                cheaper += 1
            elif g >= 5:
                expensive += 1
            else:
                similar += 1
        vtr_freq += s.vtr_freq_monthly
        market_freq += s.market_freq_monthly
        fg = s.freq_gap_pct
        if fg is not None:
            if fg >= 20:
                freq_lead += 1
            elif fg <= -20:
                freq_lag += 1

    vtr_count = sum(1 for t in tours if is_vietravel(t.cong_ty))
    mkt_count = sum(1 for t in tours if not is_vietravel(t.cong_ty))

    return CompareSummary(
        company=settings.company_name,
        total_vietravel_tours=vtr_count,
        total_market_tours=mkt_count,
        segments_with_vietravel=len(segments),
        cheaper_count=cheaper,
        expensive_count=expensive,
        similar_count=similar,
        avg_gap_pct=round(sum(gaps) / len(gaps), 1) if gaps else None,
        vtr_freq_monthly_total=round(vtr_freq, 1),
        vtr_avg_departures_per_month=round(vtr_freq / vtr_count, 1) if vtr_count else None,
        market_freq_monthly_total=round(market_freq, 1),
        freq_leading_segments=freq_lead,
        freq_lagging_segments=freq_lag,
        methodology=METHODOLOGY,
    )


@router.get("/segments")
def compare_segments(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    sort_by: str = Query("gap_pct"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = deduplicate_tours(_load_tours(db, thi_truong, tuyen_tour, diem_kh))
    segments = build_segment_stats(tours, dedup=False)
    rows = [s.to_dict() for s in segments]

    sort_key = {
        "gap_pct": lambda r: r.get("gap_pct") if r.get("gap_pct") is not None else -999,
        "freq_gap_pct": lambda r: r.get("freq_gap_pct") if r.get("freq_gap_pct") is not None else -999,
        "vietravel_avg": lambda r: r.get("vietravel_avg_day") or 0,
        "market_avg": lambda r: r.get("market_avg_day") or 0,
        "vietravel_freq": lambda r: r.get("vietravel_freq_monthly") or 0,
        "tuyen_tour": lambda r: r.get("tuyen_tour") or "",
    }.get(sort_by, lambda r: r.get("gap_pct") or -999)
    reverse = sort_by != "tuyen_tour"
    rows.sort(key=sort_key, reverse=reverse)
    return {"methodology": METHODOLOGY, "items": rows[:limit], "total": len(rows)}


@router.get("/segment-detail")
def segment_detail(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = deduplicate_tours(db.query(Tour).filter(Tour.gia != None, Tour.gia > 0).all())  # noqa: E711
    segments = {s.key: s for s in build_segment_stats(tours, dedup=False)}
    seg = segments.get(key)
    if not seg:
        return {"segment_key": key, "found": False}

    by_company: dict[str, list] = defaultdict(list)
    for e in seg.entries:
        by_company[e.cong_ty].append({
            "id": e.tour_id,
            "ten_tour": e.ten_tour,
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "price_day": e.price_day,
            "freq_monthly": e.freq_score,
            "freq_label": e.freq_label,
            "lich_kh": e.lich_kh,
            "lich_trinh": e.lich_trinh[:300] if e.lich_trinh else "",
            "link_url": e.link_url,
            "thoi_gian": e.thoi_gian,
            "is_vietravel": e.is_vietravel,
        })

    companies = []
    for co, tours_list in sorted(by_company.items(), key=lambda x: (-len(x[1]), x[0])):
        companies.append({
            "cong_ty": co,
            "is_vietravel": is_vietravel(co),
            "tour_count": len(tours_list),
            "tours": sorted(tours_list, key=lambda t: t["price_day"]),
        })

    return {
        "found": True,
        "segment": seg.to_dict(),
        "companies": companies,
        "methodology": METHODOLOGY,
    }


@router.get("/segment-tours")
def segment_tours(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tours = deduplicate_tours(db.query(Tour).filter(Tour.gia != None, Tour.gia > 0).all())  # noqa: E711
    segments = {s.key: s for s in build_segment_stats(tours, dedup=False)}
    seg = segments.get(key)
    if not seg:
        return {"segment_key": key, "tours": []}
    flat = []
    for e in seg.entries:
        flat.append({
            "id": e.tour_id,
            "cong_ty": e.cong_ty,
            "ten_tour": e.ten_tour,
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "price_day": e.price_day,
            "freq_monthly": e.freq_score,
            "lich_kh": e.lich_kh,
            "is_vietravel": e.is_vietravel,
        })
    flat.sort(key=lambda x: x["price_day"])
    return {"segment_key": key, "tours": flat, "segment": seg.to_dict()}


@router.get("/competitors")
def list_competitors(
    thi_truong: list[str] = Query([]),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = deduplicate_tours(_load_tours(db, thi_truong))
    segments = build_segment_stats(tours, dedup=False)
    stats: dict[str, dict] = {}

    for seg in segments:
        for e in seg.market_entries:
            co = e.cong_ty
            if is_vietravel(co):
                continue
            if co not in stats:
                stats[co] = {
                    "cong_ty": co,
                    "tour_count": 0,
                    "overlap_segments": 0,
                    "freq_monthly": 0.0,
                    "price_days": [],
                }
            stats[co]["tour_count"] += 1
            stats[co]["freq_monthly"] += e.freq_score
            stats[co]["price_days"].append(e.price_day)

    seg_companies: dict[str, set] = defaultdict(set)
    for seg in segments:
        for e in seg.entries:
            if not e.is_vietravel:
                seg_companies[e.cong_ty].add(seg.key)

    rows = []
    for co, s in stats.items():
        avg_day = round(sum(s["price_days"]) / len(s["price_days"]), 0) if s["price_days"] else None
        rows.append({
            "cong_ty": co,
            "tour_count": s["tour_count"],
            "overlap_segments": len(seg_companies.get(co, set())),
            "freq_monthly": round(s["freq_monthly"], 1),
            "avg_price_day": avg_day,
        })
    rows.sort(key=lambda x: (-x["overlap_segments"], -x["tour_count"]))
    return {"items": rows[:limit], "total": len(rows)}


@router.get("/competitor/{company}")
def competitor_detail(
    company: str,
    thi_truong: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = deduplicate_tours(_load_tours(db, thi_truong))
    return build_competitor_overview(tours, company)
