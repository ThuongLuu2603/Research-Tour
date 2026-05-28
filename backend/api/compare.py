from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user
from compare_cache import get_compare_context, get_segment_by_key, load_tours
from compare_engine import (
    METHODOLOGY,
    build_competitor_overview,
    deduplicate_tours,
    is_vietravel,
    normalize_departure,
    normalize_route,
    parse_segment_key,
)
from classification import collect_unmatched_values, resolve_company_name
from config import settings
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareSummary(BaseModel):
    company: str
    total_vietravel_tours: int
    vietravel_tab_tours: int
    vietravel_main_tours: int = 0
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


def _load_vtr_tours(db: Session, thi_truong: list[str], tuyen_tour: str = "", diem_kh: str = "") -> list[Tour]:
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh)
    return [t for t in ctx.tours if is_vietravel(t.cong_ty)]


@router.get("/filter-options")
def compare_filter_options(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    vtr_tours = _load_vtr_tours(db, [])
    markets = sorted({(t.thi_truong or "Khác").strip() for t in vtr_tours})
    routes_by_market: dict[str, list[str]] = defaultdict(list)
    all_routes: set[str] = set()
    deps: set[str] = set()
    for t in vtr_tours:
        m = (t.thi_truong or "Khác").strip()
        route = normalize_route(t.tuyen_tour) or m
        all_routes.add(route)
        if route not in routes_by_market[m]:
            routes_by_market[m].append(route)
        deps.add(normalize_departure(t.diem_kh))
    for m in routes_by_market:
        routes_by_market[m] = sorted(routes_by_market[m])
    return {
        "thi_truong": markets,
        "tuyen_tour": sorted(all_routes),
        "diem_kh": sorted(deps),
        "routes_by_market": dict(routes_by_market),
    }


@router.get("/classification-gaps")
def classification_gaps(
    thi_truong: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = _load_vtr_tours(db, thi_truong)
    return collect_unmatched_values(tours, vtr_only=True)


@router.get("/summary", response_model=CompareSummary)
def compare_summary(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh)
    segments = ctx.segments
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

    tours = ctx.tours
    vtr_count = sum(1 for t in tours if is_vietravel(t.cong_ty))
    vtr_tab_count = sum(
        1 for t in tours
        if (t.nguon or "") == "Vietravel" or (t.sheet_source or "") == "Vietravel"
    )
    vtr_main_count = sum(
        1 for t in tours
        if is_vietravel(t.cong_ty) and (t.nguon or "") not in ("Vietravel", "")
    )
    mkt_count = sum(1 for t in tours if not is_vietravel(t.cong_ty))

    return CompareSummary(
        company=settings.company_name,
        total_vietravel_tours=vtr_count,
        vietravel_tab_tours=vtr_tab_count,
        vietravel_main_tours=vtr_main_count,
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
    sort_dir: str = Query("desc"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh)
    rows = list(ctx.segment_rows)

    sort_key = {
        "gap_pct": lambda r: r.get("gap_pct") if r.get("gap_pct") is not None else -999,
        "freq_gap_pct": lambda r: r.get("freq_gap_pct") if r.get("freq_gap_pct") is not None else -999,
        "vietravel_avg": lambda r: r.get("vietravel_avg_day") or 0,
        "vietravel_avg_price": lambda r: r.get("vietravel_avg_price") or 0,
        "comparison_price": lambda r: r.get("comparison_price") or 0,
        "market_min_price": lambda r: r.get("market_min_price") or 0,
        "market_avg": lambda r: r.get("market_avg_day") or 0,
        "vietravel_freq": lambda r: r.get("vietravel_freq_monthly") or 0,
        "thi_truong": lambda r: r.get("thi_truong") or "",
        "tuyen_tour": lambda r: r.get("tuyen_tour") or "",
        "diem_kh": lambda r: r.get("diem_kh") or "",
        "so_ngay": lambda r: r.get("so_ngay") or 0,
    }.get(sort_by, lambda r: r.get("gap_pct") or -999)
    reverse = sort_dir != "asc"
    rows.sort(key=sort_key, reverse=reverse)
    return {"methodology": METHODOLOGY, "items": rows[:limit], "total": len(rows)}


def _segment_detail_payload(seg) -> dict:
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


@router.get("/segment-detail")
def segment_detail(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    seg = get_segment_by_key(db, key)
    if not seg:
        parsed = parse_segment_key(key)
        if parsed:
            market, route, depart = parsed
            ctx = get_compare_context(db, [market], route, depart)
            seg = ctx.segment_by_key.get(key)
    if not seg:
        return {"segment_key": key, "found": False}
    return _segment_detail_payload(seg)


@router.get("/segment-tours")
def segment_tours(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    seg = get_segment_by_key(db, key)
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


@router.get("/weekday-distribution")
def weekday_distribution(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Phân bổ đoàn KH theo thứ trong tuần — VTR vs thị trường."""
    from compare_engine import build_weekday_distribution

    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh)
    return build_weekday_distribution(ctx.tours)


@router.get("/competitors")
def list_competitors(
    thi_truong: list[str] = Query([]),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    ctx = get_compare_context(db, thi_truong)
    segments = ctx.segments
    stats: dict[str, dict] = {}

    for seg in segments:
        for e in seg.market_entries:
            co = resolve_company_name(e.cong_ty)
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
                seg_companies[resolve_company_name(e.cong_ty)].add(seg.key)

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
    ctx = get_compare_context(db, thi_truong)
    return build_competitor_overview(ctx.tours, company)
