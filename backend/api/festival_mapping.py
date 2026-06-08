"""API CRUD cho Festival Tour Mapping Rule (Quy tắc phân loại tab Lễ hội)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin
from database import get_db
from models import FestivalTourMappingRule, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/rules/festival-mapping", tags=["festival-mapping"])


class _IdAsStrMixin:
    """CockroachDB unique_rowid() vượt JS Number.MAX_SAFE — serialize string."""

    @classmethod
    def model_validate(cls, obj, **kwargs):
        return super().model_validate(obj, **kwargs)


class FestivalMappingOut(BaseModel):
    id: str
    location_keyword: str
    market_keyword: str
    route_keyword: str
    date_window_days: int
    active: bool
    note: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, r: FestivalTourMappingRule) -> "FestivalMappingOut":
        return cls(
            id=str(r.id),
            location_keyword=r.location_keyword or "",
            market_keyword=r.market_keyword or "",
            route_keyword=r.route_keyword or "",
            date_window_days=r.date_window_days or 7,
            active=bool(r.active),
            note=r.note or "",
        )


class FestivalMappingIn(BaseModel):
    location_keyword: str = Field(min_length=1, max_length=256)
    market_keyword: str = Field(default="", max_length=256)
    route_keyword: str = Field(default="", max_length=256)
    date_window_days: int = Field(default=7, ge=0, le=365)
    active: bool = True
    note: str = Field(default="", max_length=512)


@router.get("", response_model=list[FestivalMappingOut])
def list_rules(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rules = (
        db.query(FestivalTourMappingRule)
        .order_by(FestivalTourMappingRule.id.desc())
        .all()
    )
    return [FestivalMappingOut.from_model(r) for r in rules]


@router.post("", response_model=FestivalMappingOut)
def create_rule(
    body: FestivalMappingIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not body.location_keyword.strip():
        raise HTTPException(400, "Phải nhập location_keyword")
    if not body.market_keyword.strip() and not body.route_keyword.strip():
        raise HTTPException(400, "Phải có ít nhất 1 trong market_keyword hoặc route_keyword")
    rule = FestivalTourMappingRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return FestivalMappingOut.from_model(rule)


@router.put("/{rule_id}", response_model=FestivalMappingOut)
def update_rule(
    rule_id: str,
    body: FestivalMappingIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        rid_int = int(rule_id)
    except ValueError as e:
        raise HTTPException(400, f"rule_id không hợp lệ: {rule_id}") from e
    rule = db.query(FestivalTourMappingRule).filter(FestivalTourMappingRule.id == rid_int).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    return FestivalMappingOut.from_model(rule)


@router.delete("/{rule_id}")
def delete_rule(
    rule_id: str,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        rid_int = int(rule_id)
    except ValueError as e:
        raise HTTPException(400, f"rule_id không hợp lệ: {rule_id}") from e
    rule = db.query(FestivalTourMappingRule).filter(FestivalTourMappingRule.id == rid_int).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    return {"deleted": rule_id}


@router.post("/apply")
def apply_rules(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Apply mọi active mapping rules.

    Logic: mỗi rule có (location_keyword, market_keyword, route_keyword).
      1. Tìm TẤT CẢ festivals có location_text chứa location_keyword (ilike).
      2. Tìm TẤT CẢ tour matching market_keyword + route_keyword EXACT.
      3. Tour chưa có festival_slug → tag vào festival GẦN NHẤT (theo date_start)
         trong nhóm festivals đã match ở (1).
      4. Tour đã có festival_slug khác → bỏ qua (không ghi đè).
    """
    from sqlalchemy import func
    from models import Festival, Tour
    from tour_filters import market_filter_clause

    rules = (
        db.query(FestivalTourMappingRule)
        .filter(FestivalTourMappingRule.active == True)  # noqa: E712
        .all()
    )
    if not rules:
        return {"message": "Không có rule active", "rules_applied": 0, "tours_tagged": 0}

    total_tagged = 0
    rule_stats: list[dict[str, Any]] = []
    today = date.today() if False else __import__("datetime").date.today()

    for r in rules:
        loc_kw = r.location_keyword.strip()
        if not loc_kw:
            continue
        # Step 1: tìm festivals matching location
        festivals = (
            db.query(Festival)
            .filter(func.lower(Festival.location_text).like(f"%{loc_kw.lower()}%"))
            .order_by(Festival.date_start.asc())
            .all()
        )
        if not festivals:
            rule_stats.append({
                "location_keyword": loc_kw,
                "tagged": 0,
                "skip": "không có festival nào match location",
            })
            continue
        # Step 2: build query tour matching market+route
        q = db.query(Tour).filter(market_filter_clause(Tour), Tour.festival_slug.is_(None))
        mk = r.market_keyword.strip()
        rk = r.route_keyword.strip()
        if mk:
            q = q.filter(Tour.thi_truong == mk)
        if rk:
            q = q.filter(Tour.tuyen_tour == rk)
        tours = q.all()
        if not tours:
            rule_stats.append({
                "location_keyword": loc_kw,
                "festivals_matched": len(festivals),
                "tagged": 0,
                "skip": "không có tour matching market/route",
            })
            continue
        # Step 3: chọn festival GẦN NHẤT (chưa kết thúc, sắp tới)
        # Ưu tiên festival có date_end >= today; nếu không, lấy cái cuối (gần nhất quá khứ)
        upcoming = [f for f in festivals if f.date_end >= today]
        target_festival = upcoming[0] if upcoming else festivals[-1]

        for t in tours:
            t.festival_slug = target_festival.slug
            t.festival_distance_days = 0  # manual rule = trùng

        try:
            db.commit()
        except Exception as e:
            logger.exception("Apply rule %d commit fail: %s", r.id, e)
            db.rollback()
            continue

        rule_stats.append({
            "location_keyword": loc_kw,
            "festivals_matched": len(festivals),
            "target_festival_name": target_festival.name_vi,
            "tagged": len(tours),
        })
        total_tagged += len(tours)
    logger.info("Festival manual mapping: %d tours tagged across %d rules", total_tagged, len(rules))
    return {
        "message": f"Áp dụng {len(rules)} rule, tag {total_tagged} tour",
        "rules_applied": len(rules),
        "tours_tagged": total_tagged,
        "details": rule_stats,
    }
