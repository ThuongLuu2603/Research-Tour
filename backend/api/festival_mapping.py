"""API CRUD cho Festival Tour Mapping Rule (Quy tắc phân loại tab Lễ hội)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user, require_admin
from database import get_db
from models import FestivalTourMappingRule, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/rules/festival-mapping", tags=["festival-mapping"])


def _invalidate_festival_caches() -> None:
    """Issue #5 Phase A — wipe coverage/dashboard Redis caches sau CUD rule."""
    try:
        from redis_cache import redis_invalidate_pattern

        redis_invalidate_pattern("ota:festival.coverage_gap:*")
        redis_invalidate_pattern("ota:festival.dashboard:*")
    except Exception:  # noqa: BLE001
        logger.exception("redis_invalidate_pattern festival cache fail")


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
    _invalidate_festival_caches()
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
    _invalidate_festival_caches()
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
    _invalidate_festival_caches()
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
    from models import Festival, Tour, FestivalTourMapping
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
        # Step 2: tour matching market+route. BỎ điều kiện festival_slug.is_(None) — bảng
        # nối cho phép 1 tour gắn nhiều lễ; rule không còn bị engine date ghi đè.
        q = db.query(Tour).filter(market_filter_clause(Tour))
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

        # Link đã tồn tại cho (festival này, các tour) — tránh vi phạm unique.
        tour_ids = [t.id for t in tours]
        existing = {
            row[0] for row in db.query(FestivalTourMapping.tour_id).filter(
                FestivalTourMapping.festival_id == target_festival.id,
                FestivalTourMapping.tour_id.in_(tour_ids),
            ).all()
        }
        new_links = []
        for t in tours:
            # festival_slug = cache PRIMARY: chỉ set khi tour chưa có (không clobber lễ
            # primary do date-engine chọn). Liên kết rule luôn vào bảng nối.
            if t.festival_slug is None:
                t.festival_slug = target_festival.slug
                t.festival_distance_days = 0
            if t.id not in existing:
                new_links.append({
                    "festival_id": target_festival.id, "tour_id": t.id,
                    "festival_slug": target_festival.slug, "distance_days": 0, "source": "rule",
                    # bulk_insert_mappings bỏ qua Python default → set created_at tay
                    # nếu không NULL vi phạm NOT NULL → rollback (bảng nối rỗng).
                    "created_at": datetime.utcnow(),
                })
        if new_links:
            db.bulk_insert_mappings(FestivalTourMapping, new_links)

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
    _invalidate_festival_caches()
    return {
        "message": f"Áp dụng {len(rules)} rule, tag {total_tagged} tour",
        "rules_applied": len(rules),
        "tours_tagged": total_tagged,
        "details": rule_stats,
    }


# ── Issue #5 Phase A: auto-suggest + bulk-create ───────────────────────────


class MappingSuggestion(BaseModel):
    festival_slug: str
    festival_name: str
    location_text: str
    suggested_location_keyword: str
    suggested_market: str
    suggested_route: str
    confidence: float
    tour_count: int
    reasoning: str


class MappingSuggestionsOut(BaseModel):
    suggestions: list[MappingSuggestion]


class BulkMappingRuleIn(BaseModel):
    location_keyword: str
    market_keyword: str = ""
    route_keyword: str = ""
    date_window_days: int = 7
    active: bool = True
    note: str = ""


class BulkMappingCreateIn(BaseModel):
    rules: list[BulkMappingRuleIn]


class BulkMappingCreateOut(BaseModel):
    inserted: int
    ids: list[str]
    skipped: list[dict[str, str]] = []


@router.post("/auto-suggest", response_model=MappingSuggestionsOut)
def auto_suggest_rules(
    limit: int = 20,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Suggest mapping rules cho top under-served festivals.

    Logic: lấy festival upcoming chưa có rule match → tìm top tour cluster
    (market, route) trong tuyen_tour chứa keyword → suggest.
    """
    from festival_tagging import suggest_festival_mapping_rules

    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    items = suggest_festival_mapping_rules(db, limit=limit)
    return MappingSuggestionsOut(suggestions=[MappingSuggestion(**s) for s in items])


@router.post("/bulk-create", response_model=BulkMappingCreateOut)
def bulk_create_rules(
    body: BulkMappingCreateIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Bulk insert FestivalTourMappingRule. Trả inserted count + ids."""
    inserted_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    for idx, r in enumerate(body.rules):
        loc_kw = (r.location_keyword or "").strip()
        if not loc_kw:
            skipped.append({"index": str(idx), "reason": "location_keyword rỗng"})
            continue
        mk = (r.market_keyword or "").strip()
        rk = (r.route_keyword or "").strip()
        if not mk and not rk:
            skipped.append({
                "index": str(idx),
                "reason": "phải có ít nhất 1 trong market_keyword/route_keyword",
            })
            continue
        rule = FestivalTourMappingRule(
            location_keyword=loc_kw,
            market_keyword=mk,
            route_keyword=rk,
            date_window_days=max(0, min(365, int(r.date_window_days or 7))),
            active=bool(r.active),
            note=(r.note or "")[:512],
        )
        db.add(rule)
        try:
            db.flush()
            inserted_ids.append(str(rule.id))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            skipped.append({"index": str(idx), "reason": f"insert lỗi: {e}"})
    try:
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(500, f"Bulk commit fail: {e}") from e
    _invalidate_festival_caches()
    return BulkMappingCreateOut(
        inserted=len(inserted_ids),
        ids=inserted_ids,
        skipped=skipped,
    )
