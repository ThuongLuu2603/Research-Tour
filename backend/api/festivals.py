"""API endpoints cho module Sự kiện & Lễ hội (Phase 1)."""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin
from database import get_db
from models import Festival, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/festivals", tags=["festivals"])


class FestivalOut(BaseModel):
    id: str  # bigint → string cho JS safe
    slug: str
    name_vi: str
    name_en: str
    date_start: date_type
    date_end: date_type
    is_lunar: bool
    location_text: str
    province_code: str
    region: str
    category: str
    description: str
    image_url: str
    source_url: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, f: Festival) -> "FestivalOut":
        return cls(
            id=str(f.id),
            slug=f.slug,
            name_vi=f.name_vi,
            name_en=f.name_en or "",
            date_start=f.date_start,
            date_end=f.date_end,
            is_lunar=bool(f.is_lunar),
            location_text=f.location_text or "",
            province_code=f.province_code or "",
            region=f.region or "",
            category=f.category or "other",
            description=f.description or "",
            image_url=f.image_url or "",
            source_url=f.source_url or "",
        )


@router.get("", response_model=list[FestivalOut])
def list_festivals(
    from_date: date_type | None = Query(None, alias="from"),
    to_date: date_type | None = Query(None, alias="to"),
    region: str | None = Query(None, description="bac|trung|nam"),
    category: str | None = Query(None),
    province: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List events theo khoảng ngày + filter.

    Mặc định: từ hôm nay đến cuối năm sau (~18 tháng).
    """
    today = date_type.today()
    if from_date is None:
        from_date = today
    if to_date is None:
        to_date = date_type(today.year + 1, 12, 31)

    q = db.query(Festival).filter(
        and_(
            # Overlap: event date_range overlap với [from_date, to_date]
            Festival.date_start <= to_date,
            Festival.date_end >= from_date,
        )
    )
    if region:
        q = q.filter(Festival.region == region)
    if category:
        q = q.filter(Festival.category == category)
    if province:
        q = q.filter(Festival.province_code == province)
    rows = q.order_by(Festival.date_start.asc()).limit(limit).all()
    return [FestivalOut.from_model(r) for r in rows]


@router.get("/{slug}", response_model=FestivalOut)
def get_festival(
    slug: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    f = db.query(Festival).filter(Festival.slug == slug).first()
    if not f:
        raise HTTPException(404, f"Festival {slug} không tồn tại")
    return FestivalOut.from_model(f)


class FestivalStats(BaseModel):
    total: int
    by_region: dict[str, int]
    by_category: dict[str, int]
    by_month: dict[str, int]  # "2026-06" -> count
    upcoming_30d: int
    upcoming_90d: int


@router.get("/stats/summary", response_model=FestivalStats)
def festival_stats(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = date_type.today()
    end = date_type(today.year + 1, 12, 31)
    rows = (
        db.query(Festival)
        .filter(
            and_(
                Festival.date_start <= end,
                Festival.date_end >= today,
            )
        )
        .all()
    )
    by_region: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_month: dict[str, int] = {}
    up30 = 0
    up90 = 0
    d30 = today + timedelta(days=30)
    d90 = today + timedelta(days=90)
    for f in rows:
        region_key = f.region or "unknown"
        by_region[region_key] = by_region.get(region_key, 0) + 1
        cat_key = f.category or "other"
        by_category[cat_key] = by_category.get(cat_key, 0) + 1
        month_key = f.date_start.strftime("%Y-%m")
        by_month[month_key] = by_month.get(month_key, 0) + 1
        if f.date_start <= d30 and f.date_end >= today:
            up30 += 1
        if f.date_start <= d90 and f.date_end >= today:
            up90 += 1
    return FestivalStats(
        total=len(rows),
        by_region=by_region,
        by_category=by_category,
        by_month=by_month,
        upcoming_30d=up30,
        upcoming_90d=up90,
    )


@router.post("/refresh")
def refresh_festivals(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Manual trigger scrape vietnam.travel/event → upsert festivals (background).

    Chạy nền vì scrape có thể 2-5 phút (24 list page × rate limit 1.5s + 30-60 detail
    page × 1.5s + retry SSL). Endpoint trả ngay, user theo dõi qua /api/scraper/jobs.
    """
    import threading
    from scheduler import _run_festival_scrape

    threading.Thread(target=_run_festival_scrape, daemon=True, name="festival-scrape-manual").start()
    return {
        "message": "Đã bắt đầu scrape nền — kiểm tra Job History (Vận hành) hoặc đợi 2-5 phút rồi reload trang.",
        "started": True,
    }


# ── Phase 2: Cross-ref tour ─────────────────────────────────────────────────


class TourLite(BaseModel):
    id: str
    cong_ty: str
    thi_truong: str
    tuyen_tour: str
    ten_tour: str
    diem_kh: str
    province_code: str
    gia: float | None
    so_ngay: float | None
    nguon: str
    festival_distance_days: int | None


@router.get("/{slug}/tours", response_model=list[TourLite])
def festival_tours(
    slug: str,
    company: str | None = Query(None, description="Filter theo cong_ty"),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List tour gắn lễ này — từ BẢNG NỐI (nguồn sự thật, khớp đúng địa điểm/ngày
    nghỉ), loại market 'Không xác định' + 'DV lẻ' như So sánh VTR."""
    from models import Festival, FestivalTourMapping, Tour
    from tour_filters import market_filter_clause

    f = db.query(Festival).filter(Festival.slug == slug).first()
    if not f:
        raise HTTPException(404, "Festival không tồn tại")
    q = (
        db.query(Tour)
        .join(FestivalTourMapping, FestivalTourMapping.tour_id == Tour.id)
        .filter(FestivalTourMapping.festival_id == f.id)
        .filter(market_filter_clause(Tour))
    )
    if company:
        q = q.filter(Tour.cong_ty.ilike(f"%{company}%"))
    rows = q.order_by(Tour.cong_ty.asc(), Tour.gia.asc().nullslast()).limit(500).all()
    return [
        TourLite(
            id=str(t.id),
            cong_ty=t.cong_ty or "",
            thi_truong=t.thi_truong or "",
            tuyen_tour=t.tuyen_tour or "",
            ten_tour=t.ten_tour or "",
            diem_kh=t.diem_kh or "",
            province_code=t.province_code or "",
            gia=t.gia,
            so_ngay=t.so_ngay,
            nguon=t.nguon or "",
            festival_distance_days=t.festival_distance_days,
        )
        for t in rows
    ]


class FestivalCompanyAgg(BaseModel):
    cong_ty: str
    is_vtr: bool = False
    products: int = 0
    departures: int = 0
    price_from: float | None = None
    link: str = ""


class FestivalSummary(BaseModel):
    slug: str
    name: str
    total_tours: int
    by_company: dict[str, int]
    companies: list[FestivalCompanyAgg] = []
    avg_price: float | None
    vtr_tours: int
    competitor_tours: int


@router.get("/{slug}/summary", response_model=FestivalSummary)
def festival_summary(
    slug: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stats cho 1 festival: tour gắn theo công ty, VTR vs competitor."""
    from festival_tagging import get_festival_tours_summary

    result = get_festival_tours_summary(db, slug)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return FestivalSummary(**result)


class CoverageGapItem(BaseModel):
    slug: str
    name: str
    date_start: str
    date_end: str
    region: str
    location: str = ""
    vtr_tours: int
    competitor_tours: int
    # Issue #5 Phase A: split tagged vs implied
    vtr_tours_tagged: int = 0
    vtr_tours_implied: int = 0
    competitor_tours_tagged: int = 0
    competitor_tours_implied: int = 0
    mapping_rule_ids: list[str] = []
    has_mapping_rule: bool = False
    # Frontend (FestivalsPage.tsx) reads `has_rule`; keep `has_mapping_rule` for
    # back-compat. Both serialized identically by _compute_coverage_gap.
    has_rule: bool = False
    # Frontend reads `location_text ?? location`; expose alias for new clients.
    location_text: str = ""
    top_competitors: dict[str, int]
    gap_score: float


class CoverageGapMappingSummary(BaseModel):
    total_festivals: int
    festivals_with_rule: int
    festivals_without_rule: int


## MappingSuggestion / BulkMappingRule schemas live in api/festival_mapping.py
## để gần endpoint hơn (mounted dưới /api/admin/rules/festival-mapping).


@router.get("/insights/dashboard-summary")
def dashboard_summary(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Smart dashboard cho landing tab — alerts + quick stats + data quality."""
    from festival_insights import get_dashboard_summary

    return get_dashboard_summary(db)


@router.get("/insights/coverage-gap", response_model=list[CoverageGapItem])
def coverage_gap(
    limit: int = Query(30, ge=1, le=100),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Coverage gap: festival mà competitor cover nhưng VTR chưa.

    Sort theo gap_score desc — festival VTR đang thiếu nhất ở đầu.
    """
    from festival_tagging import get_coverage_gap

    return get_coverage_gap(db, limit=limit)


@router.get(
    "/insights/coverage-gap/mapping-summary",
    response_model=CoverageGapMappingSummary,
)
def coverage_gap_mapping_summary(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue #5 Phase A — How many festivals have/lack a mapping rule."""
    from festival_tagging import get_coverage_gap_mapping_summary

    return CoverageGapMappingSummary(**get_coverage_gap_mapping_summary(db))


## NOTE: auto-suggest và bulk-create endpoints mounted trong api/festival_mapping.py
## để share /api/admin/rules/festival-mapping/* namespace với CRUD hiện có.


@router.post("/insights/retag")
def retag_festivals(
    only_untagged: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Trigger tagging engine manual. Cron tự chạy daily sau sync chain."""
    from festival_tagging import tag_tours_with_festivals

    stats = tag_tours_with_festivals(db, only_untagged=only_untagged)
    return {"message": "Tagging hoàn tất", **stats}


# ── Phase 3: Insight engine ────────────────────────────────────────────────


@router.get("/insights/pricing-premium")
def pricing_premium(
    top_n: int = Query(20, ge=5, le=100),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC#2 — Premium % của tour gắn lễ vs không gắn lễ theo (TT, Tuyến)."""
    from festival_insights import get_pricing_premium

    return get_pricing_premium(db, top_n=top_n)


@router.get("/insights/demand-forecast")
def demand_forecast(
    months_ahead: int = Query(6, ge=1, le=12),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC#3 — Forecast tháng peak lễ + suggest inventory."""
    from festival_insights import get_demand_forecast

    return get_demand_forecast(db, months_ahead=months_ahead)


@router.get("/insights/marketing-calendar")
def marketing_calendar(
    months_ahead: int = Query(12, ge=1, le=24),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC#5 — Marketing calendar 12 tháng + suggested tour VTR push."""
    from festival_insights import get_marketing_calendar

    return get_marketing_calendar(db, months_ahead=months_ahead)


@router.get("/insights/heatmap")
def region_heatmap(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC#6 — Heatmap mật độ lễ × tour theo vùng (bac/trung/nam)."""
    from festival_insights import get_region_heatmap

    return get_region_heatmap(db)


@router.get("/insights/lunar-planner")
def lunar_planner(
    years_ahead: int = Query(3, ge=1, le=5),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """UC#7 — Long-range planner: lễ âm lịch 3-5 năm tới (Tết, Trung Thu, ...).

    Note: Cần chạy POST /insights/lunar-seed 1 lần để upsert lễ âm vào DB.
    """
    from lunar_festivals import get_lunar_planner

    return {"events": get_lunar_planner(db, years_ahead=years_ahead)}


@router.post("/insights/lunar-seed")
def lunar_seed(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Seed lễ âm lịch (Tết, Vu Lan…) + ngày nghỉ lễ dương (Tết dương, 30/4, 1/5,
    Quốc khánh) cho dải năm vào festivals table."""
    from lunar_festivals import seed_lunar_festivals, seed_solar_holidays

    lunar = seed_lunar_festivals(db)
    solar = seed_solar_holidays(db)
    return {
        "message": "Seed lễ âm + nghỉ lễ dương hoàn tất",
        "inserted": lunar["inserted"] + solar["inserted"],
        "skipped": lunar["skipped"] + solar["skipped"],
        "lunar": lunar,
        "solar": solar,
    }
