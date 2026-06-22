"""Tour Market Lab API."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, load_only

from api.auth import get_current_user
from database import get_db
from market_lab_cache import get_market_lab_overview_cached
from market_lab_engine import get_supply_calendar
from models import RouteDailyMetrics, SegmentSnapshot, User

router = APIRouter(prefix="/api/market-lab", tags=["market-lab"])


@router.get("/overview")
def overview(
    grain: str = Query("route", pattern="^(route|market)$"),
    tab: str = Query("opportunity", pattern="^(opportunity|operating)$"),
    thi_truong: str | None = Query(None),
    diem_kh: str | None = Query(None),
    hide_suspect: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return get_market_lab_overview_cached(
        db, grain=grain, tab=tab, thi_truong=thi_truong or None, diem_kh=diem_kh or None, hide_suspect=hide_suspect,
    )


@router.get("/supply-calendar")
def supply_calendar(
    thi_truong: str = Query(..., min_length=1),
    tuyen_tour: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return get_supply_calendar(db, thi_truong, tuyen_tour)


@router.get("/weekly-brief")
def weekly_brief(
    thi_truong: str | None = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    data = get_market_lab_overview_cached(db, grain="route", tab="opportunity", thi_truong=thi_truong or None)
    return data.get("weekly_brief", {})


@router.get("/route-history")
def route_history(
    route_key: str = Query(..., min_length=1),
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lịch sử metrics theo tuyến — dùng cho trend chart 30 ngày."""
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(RouteDailyMetrics)
        .options(load_only(
            RouteDailyMetrics.snapshot_date,
            RouteDailyMetrics.market_departures_monthly,
            RouteDailyMetrics.vtr_departures_monthly,
            RouteDailyMetrics.avg_gap_pct,
            RouteDailyMetrics.freq_gap_pct,
            RouteDailyMetrics.market_price_day,
            RouteDailyMetrics.phase,
            RouteDailyMetrics.opportunity_score,
            RouteDailyMetrics.competitor_count,
        ))
        .filter(
            RouteDailyMetrics.route_key == route_key,
            RouteDailyMetrics.snapshot_date >= since,
        )
        .order_by(RouteDailyMetrics.snapshot_date)
        .all()
    )
    return {
        "route_key": route_key,
        "days": days,
        "points": [
            {
                "date": r.snapshot_date.isoformat(),
                "market_dep": round(r.market_departures_monthly, 1),
                "vtr_dep": round(r.vtr_departures_monthly, 1),
                "gap_pct": r.avg_gap_pct,
                "freq_gap_pct": r.freq_gap_pct,
                "market_price_day": r.market_price_day,
                "phase": r.phase,
                "opportunity_score": round(r.opportunity_score, 1) if r.opportunity_score else 0,
            }
            for r in rows
        ],
    }


@router.get("/segment-history")
def segment_history(
    segment_key: str = Query(..., min_length=1),
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Lịch sử segment snapshot — dùng cho mini chart trong So Sánh VTR."""
    since = date.today() - timedelta(days=days)
    rows = (
        db.query(SegmentSnapshot)
        .options(load_only(
            SegmentSnapshot.snapshot_date,
            SegmentSnapshot.gap_pct,
            SegmentSnapshot.freq_gap_pct,
            SegmentSnapshot.vtr_avg_price,
            SegmentSnapshot.comparison_price,
            SegmentSnapshot.vtr_avg_departures,
            SegmentSnapshot.market_avg_departures,
            SegmentSnapshot.vtr_tour_count,
            SegmentSnapshot.market_tour_count,
        ))
        .filter(
            SegmentSnapshot.segment_key == segment_key,
            SegmentSnapshot.snapshot_date >= since,
        )
        .order_by(SegmentSnapshot.snapshot_date)
        .all()
    )
    return {
        "segment_key": segment_key,
        "points": [
            {
                "date": r.snapshot_date.isoformat(),
                "gap_pct": r.gap_pct,
                "freq_gap_pct": r.freq_gap_pct,
                "vtr_price": r.vtr_avg_price,
                "market_price": r.comparison_price,
                "vtr_dep": r.vtr_avg_departures,
                "market_dep": r.market_avg_departures,
            }
            for r in rows
        ],
    }
