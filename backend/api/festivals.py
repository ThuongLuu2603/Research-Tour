"""API endpoints cho module Sự kiện & Lễ hội (Phase 1)."""
from __future__ import annotations

import logging
from datetime import date as date_type, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from auth import User, get_current_user, require_admin
from database import get_db
from models import Festival

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
    """Manual trigger scrape vietnam.travel/event → upsert festivals."""
    from festival_scraper import run_festival_scrape

    try:
        result = run_festival_scrape(db)
        return {"message": "Scrape hoàn tất", **result}
    except Exception as e:
        logger.exception("Festival scrape lỗi: %s", e)
        raise HTTPException(502, f"Scrape thất bại: {e}") from e
