from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import require_admin
from classification import (
    apply_all_rules_to_tours,
    apply_company_aliases_to_tours,
    apply_departure_aliases_to_tours,
    apply_duration_aliases_to_tours,
    apply_classification_rules_to_tours,
    classification_rules_status,
    invalidate_classification_cache,
    seed_company_aliases_from_defaults,
    seed_departure_aliases_from_defaults,
    seed_duration_aliases_from_defaults,
    seed_market_rules_from_hardcode,
    seed_route_rules_from_bundle,
)
from database import get_db
from models import CompanyAliasRule, DepartureAliasRule, DurationAliasRule, MarketKeywordRule, RouteKeywordRule, User
from sheets_rules_sync import (
    import_market_rules_from_sheet,
    import_route_rules_to_db,
    push_market_rules_to_sheet,
    push_route_rules_to_sheet,
    sync_all_from_sheet,
    sync_all_to_sheet,
)

router = APIRouter(prefix="/api/admin/rules", tags=["rules-admin"])


@router.get("/status")
def rules_runtime_status(_: User = Depends(require_admin)):
    """Nguồn alias đang dùng lúc chạy (DB vs mặc định code khi bảng trống)."""
    return classification_rules_status()


class MarketRuleOut(BaseModel):
    id: int
    market: str
    keyword: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}


class MarketRuleIn(BaseModel):
    market: str = Field(max_length=128)
    keyword: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


class RouteRuleOut(BaseModel):
    id: int
    thi_truong: str
    tuyen_tour: str
    keywords: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}


class RouteRuleIn(BaseModel):
    thi_truong: str = Field(max_length=128)
    tuyen_tour: str = Field(max_length=256)
    keywords: str = Field(max_length=512, description="Các từ khóa cách nhau bởi dấu phẩy, TẤT CẢ phải có trong tên tour")
    active: bool = True
    sort_order: int = 0


def _try_push_market(db: Session) -> str | None:
    try:
        n = push_market_rules_to_sheet(db)
        return f"Đã ghi {n} rule thị trường lên Sheet"
    except Exception as e:
        return f"Cảnh báo: không ghi được Sheet thị trường — {e}"


def _try_push_route(db: Session) -> str | None:
    try:
        n = push_route_rules_to_sheet(db)
        return f"Đã ghi {n} rule tuyến tour lên Sheet"
    except Exception as e:
        return f"Cảnh báo: không ghi được Sheet tuyến tour — {e}"


def _auto_apply_tours(db: Session, enabled: bool, scope: str = "all") -> dict | None:
    """Áp dụng quy tắc lên tour — chạy nền (~8k tour, tránh timeout HTTP)."""
    if not enabled:
        return None
    import logging
    import threading

    from database import SessionLocal

    log = logging.getLogger(__name__)

    def _work() -> None:
        session = SessionLocal()
        try:
            if scope in ("market", "route"):
                apply_classification_rules_to_tours(session)
            elif scope == "company":
                apply_company_aliases_to_tours(session)
            elif scope == "departure":
                apply_departure_aliases_to_tours(session)
            elif scope == "duration":
                apply_duration_aliases_to_tours(session)
            else:
                apply_all_rules_to_tours(session)
        except Exception:
            log.exception("auto_apply_tours failed scope=%s", scope)
        finally:
            session.close()

    threading.Thread(target=_work, daemon=True, name=f"apply-rules-{scope}").start()
    return {"started": True, "message": "Đang áp dụng quy tắc lên tour (chạy nền)…"}


# ── Market rules ──────────────────────────────────────────────────────────────

@router.get("/market", response_model=list[MarketRuleOut])
def list_market_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(MarketKeywordRule).order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id).all()


@router.post("/market", response_model=MarketRuleOut)
def create_market_rule(
    body: MarketRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = MarketKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    if push_sheet:
        _try_push_market(db)
    _auto_apply_tours(db, auto_apply, scope="market")
    return rule


@router.patch("/market/{rule_id}", response_model=MarketRuleOut)
def update_market_rule(
    rule_id: int,
    body: MarketRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    if push_sheet:
        _try_push_market(db)
    _auto_apply_tours(db, auto_apply, scope="market")
    return rule


@router.delete("/market/{rule_id}")
def delete_market_rule(
    rule_id: int,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    msg = _try_push_market(db) if push_sheet else None
    stats = _auto_apply_tours(db, auto_apply, scope="market")
    return {"deleted": rule_id, "sheet_sync": msg, "tours_apply": stats}


# ── Route rules ───────────────────────────────────────────────────────────────

@router.get("/route", response_model=list[RouteRuleOut])
def list_route_rules(
    thi_truong: str = "",
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(RouteKeywordRule)
    if thi_truong:
        q = q.filter(RouteKeywordRule.thi_truong == thi_truong)
    return q.order_by(RouteKeywordRule.sort_order, RouteKeywordRule.id).all()


@router.post("/route", response_model=RouteRuleOut)
def create_route_rule(
    body: RouteRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = RouteKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    if push_sheet:
        _try_push_route(db)
    _auto_apply_tours(db, auto_apply, scope="route")
    return rule


@router.patch("/route/{rule_id}", response_model=RouteRuleOut)
def update_route_rule(
    rule_id: int,
    body: RouteRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    if push_sheet:
        _try_push_route(db)
    _auto_apply_tours(db, auto_apply, scope="route")
    return rule


@router.delete("/route/{rule_id}")
def delete_route_rule(
    rule_id: int,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    msg = _try_push_route(db) if push_sheet else None
    stats = _auto_apply_tours(db, auto_apply, scope="route")
    return {"deleted": rule_id, "sheet_sync": msg, "tours_apply": stats}


# ── Sync endpoints ────────────────────────────────────────────────────────────

@router.post("/seed-market-defaults")
def seed_market_defaults(
    push_sheet: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    count = seed_market_rules_from_hardcode()
    msg = None
    if push_sheet and count >= 0:
        msg = _try_push_market(db)
    return {
        "imported": count,
        "message": f"Đã import {count} keyword mặc định" if count else "DB đã có rules",
        "sheet_sync": msg,
    }


@router.post("/seed-route-defaults")
def seed_route_defaults(
    auto_apply: bool = Query(True),
    force: bool = Query(False, description="Ghi đè toàn bộ rule tuyến trong DB bằng bản bundle"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Nạp quy tắc tuyến từ bundle JSON vào Supabase (không đọc Google Sheet)."""
    count = seed_route_rules_from_bundle(db, force=force)
    tours = _auto_apply_tours(db, auto_apply, scope="route") if count else None
    return {
        "imported": count,
        "message": f"Đã nạp {count} rule tuyến tour vào DB" if count else "DB đã có rules (bỏ qua)",
        "tours_apply": tours,
    }


@router.post("/sync-route-from-sheet")
def sync_route_from_sheet(
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        count = import_route_rules_to_db(db)
        tours = _auto_apply_tours(db, auto_apply, scope="route")
        return {"imported": count, "message": f"Đã kéo {count} rule tuyến tour từ Sheet → DB", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đọc Google Sheet: {e}") from e


@router.post("/sync-route-to-sheet")
def sync_route_to_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = push_route_rules_to_sheet(db)
        return {"pushed": count, "message": f"Đã ghi {count} rule tuyến tour từ DB → Sheet 'Điểm tuyến Tour'"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi ghi Google Sheet: {e}") from e


@router.post("/sync-market-from-sheet")
def sync_market_from_sheet(
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        count = import_market_rules_from_sheet(db)
        tours = _auto_apply_tours(db, auto_apply, scope="market")
        return {"imported": count, "message": f"Đã kéo {count} rule thị trường từ Sheet → DB", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đọc Google Sheet: {e}") from e


@router.post("/sync-market-to-sheet")
def sync_market_to_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = push_market_rules_to_sheet(db)
        return {"pushed": count, "message": f"Đã ghi {count} rule thị trường từ DB → Sheet 'Quy tắc Thị trường'"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi ghi Google Sheet: {e}") from e


@router.post("/sync-all-from-sheet")
def sync_all_from_sheet_endpoint(
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = sync_all_from_sheet(db)
        tours = _auto_apply_tours(db, auto_apply, scope="all")
        return {**result, "message": "Đã đồng bộ Sheet → DB (thị trường + tuyến tour)", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ từ Sheet: {e}") from e


@router.post("/sync-all-to-sheet")
def sync_all_to_sheet_endpoint(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = sync_all_to_sheet(db)
        return {**result, "message": "Đã đồng bộ DB → Sheet (thị trường + tuyến tour)"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ lên Sheet: {e}") from e


# ── Company alias rules ──────────────────────────────────────────────────────

class CompanyRuleOut(BaseModel):
    id: int
    canonical_name: str
    alias: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}


class CompanyRuleIn(BaseModel):
    canonical_name: str = Field(max_length=128)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/company", response_model=list[CompanyRuleOut])
def list_company_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(CompanyAliasRule)
        .order_by(CompanyAliasRule.sort_order, CompanyAliasRule.canonical_name, CompanyAliasRule.alias)
        .all()
    )


@router.post("/company", response_model=CompanyRuleOut)
def create_company_rule(
    body: CompanyRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = CompanyAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="company")
    return rule


@router.put("/company/{rule_id}", response_model=CompanyRuleOut)
def update_company_rule(
    rule_id: int,
    body: CompanyRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(CompanyAliasRule).filter(CompanyAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="company")
    return rule


@router.delete("/company/{rule_id}")
def delete_company_rule(
    rule_id: int,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(CompanyAliasRule).filter(CompanyAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    stats = _auto_apply_tours(db, auto_apply, scope="company")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/company/seed-defaults")
def seed_company_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_company_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias mặc định"}


@router.post("/company/apply-to-tours")
def apply_company_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_company_aliases_to_tours(db)
    return {"updated": updated, "message": f"Đã chuẩn hóa tên công ty cho {updated} tour"}


# ── Departure alias rules (Điểm KH) ──────────────────────────────────────────

class DepartureRuleOut(BaseModel):
    id: int
    canonical_name: str
    alias: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}


class DepartureRuleIn(BaseModel):
    canonical_name: str = Field(max_length=128)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/departure", response_model=list[DepartureRuleOut])
def list_departure_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(DepartureAliasRule)
        .order_by(DepartureAliasRule.sort_order, DepartureAliasRule.canonical_name, DepartureAliasRule.alias)
        .all()
    )


@router.post("/departure", response_model=DepartureRuleOut)
def create_departure_rule(
    body: DepartureRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = DepartureAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="departure")
    return rule


@router.put("/departure/{rule_id}", response_model=DepartureRuleOut)
def update_departure_rule(
    rule_id: int,
    body: DepartureRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DepartureAliasRule).filter(DepartureAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="departure")
    return rule


@router.delete("/departure/{rule_id}")
def delete_departure_rule(
    rule_id: int,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DepartureAliasRule).filter(DepartureAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    stats = _auto_apply_tours(db, auto_apply, scope="departure")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/departure/seed-defaults")
def seed_departure_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_departure_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias điểm KH mặc định"}


@router.post("/departure/apply-to-tours")
def apply_departure_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_departure_aliases_to_tours(db)
    return {"updated": updated, "message": f"Đã chuẩn hóa điểm khởi hành cho {updated} tour"}


@router.post("/apply-classification-to-tours")
def apply_classification_endpoint(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return apply_all_rules_to_tours(db)


# ── Duration alias rules (Thời gian) ─────────────────────────────────────────

class DurationRuleOut(BaseModel):
    id: int
    canonical_days: float
    alias: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}


class DurationRuleIn(BaseModel):
    canonical_days: float = Field(gt=0, le=45)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/duration", response_model=list[DurationRuleOut])
def list_duration_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(DurationAliasRule)
        .order_by(DurationAliasRule.sort_order, DurationAliasRule.canonical_days, DurationAliasRule.alias)
        .all()
    )


@router.post("/duration", response_model=DurationRuleOut)
def create_duration_rule(
    body: DurationRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = DurationAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="duration")
    return rule


@router.put("/duration/{rule_id}", response_model=DurationRuleOut)
def update_duration_rule(
    rule_id: int,
    body: DurationRuleIn,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DurationAliasRule).filter(DurationAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    _auto_apply_tours(db, auto_apply, scope="duration")
    return rule


@router.delete("/duration/{rule_id}")
def delete_duration_rule(
    rule_id: int,
    auto_apply: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DurationAliasRule).filter(DurationAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    stats = _auto_apply_tours(db, auto_apply, scope="duration")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/duration/seed-defaults")
def seed_duration_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_duration_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias thời gian mặc định"}


@router.post("/duration/apply-to-tours")
def apply_duration_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_duration_aliases_to_tours(db)
    return {"updated": updated, "message": f"Đã chuẩn hóa số ngày cho {updated} tour"}


@router.get("/unmatched")
def list_unmatched_rules(
    scope: str = Query("company", pattern="^(company|departure|duration|all)$"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Giá trị từ tour chưa khớp alias — dùng kéo thả gán thủ công."""
    from classification import collect_unmatched_values
    from models import Tour

    tours = db.query(Tour).all()
    data = collect_unmatched_values(tours, vtr_only=False)
    if scope == "company":
        return {"scope": scope, "items": data["cong_ty"]}
    if scope == "departure":
        return {"scope": scope, "items": data["diem_kh"]}
    if scope == "duration":
        return {"scope": scope, "items": data["thoi_gian"]}
    return {"scope": "all", **data}
