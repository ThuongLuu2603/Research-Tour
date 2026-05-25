from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import require_admin
from classification import invalidate_classification_cache, seed_market_rules_from_hardcode
from database import get_db
from models import MarketKeywordRule, RouteKeywordRule, User
from sheets_rules_sync import (
    import_market_rules_from_sheet,
    import_route_rules_to_db,
    push_market_rules_to_sheet,
    push_route_rules_to_sheet,
    sync_all_from_sheet,
    sync_all_to_sheet,
)

router = APIRouter(prefix="/api/admin/rules", tags=["rules-admin"])


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


# ── Market rules ──────────────────────────────────────────────────────────────

@router.get("/market", response_model=list[MarketRuleOut])
def list_market_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(MarketKeywordRule).order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id).all()


@router.post("/market", response_model=MarketRuleOut)
def create_market_rule(
    body: MarketRuleIn,
    push_sheet: bool = Query(True),
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
    return rule


@router.patch("/market/{rule_id}", response_model=MarketRuleOut)
def update_market_rule(
    rule_id: int,
    body: MarketRuleIn,
    push_sheet: bool = Query(True),
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
    return rule


@router.delete("/market/{rule_id}")
def delete_market_rule(
    rule_id: int,
    push_sheet: bool = Query(True),
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
    return {"deleted": rule_id, "sheet_sync": msg}


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
    push_sheet: bool = Query(True),
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
    return rule


@router.patch("/route/{rule_id}", response_model=RouteRuleOut)
def update_route_rule(
    rule_id: int,
    body: RouteRuleIn,
    push_sheet: bool = Query(True),
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
    return rule


@router.delete("/route/{rule_id}")
def delete_route_rule(
    rule_id: int,
    push_sheet: bool = Query(True),
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
    return {"deleted": rule_id, "sheet_sync": msg}


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


@router.post("/sync-route-from-sheet")
def sync_route_from_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = import_route_rules_to_db(db)
        return {"imported": count, "message": f"Đã kéo {count} rule tuyến tour từ Sheet → DB"}
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
def sync_market_from_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = import_market_rules_from_sheet(db)
        return {"imported": count, "message": f"Đã kéo {count} rule thị trường từ Sheet → DB"}
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
def sync_all_from_sheet_endpoint(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = sync_all_from_sheet(db)
        return {**result, "message": "Đã đồng bộ Sheet → DB (thị trường + tuyến tour)"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ từ Sheet: {e}") from e


@router.post("/sync-all-to-sheet")
def sync_all_to_sheet_endpoint(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = sync_all_to_sheet(db)
        return {**result, "message": "Đã đồng bộ DB → Sheet (thị trường + tuyến tour)"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ lên Sheet: {e}") from e
