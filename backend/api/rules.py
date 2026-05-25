from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import require_admin
from classification import invalidate_classification_cache, seed_market_rules_from_hardcode
from database import get_db
from models import MarketKeywordRule, RouteKeywordRule, User

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


# ── Market rules ──────────────────────────────────────────────────────────────

@router.get("/market", response_model=list[MarketRuleOut])
def list_market_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(MarketKeywordRule).order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id).all()


@router.post("/market", response_model=MarketRuleOut)
def create_market_rule(body: MarketRuleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = MarketKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    return rule


@router.patch("/market/{rule_id}", response_model=MarketRuleOut)
def update_market_rule(rule_id: int, body: MarketRuleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    return rule


@router.delete("/market/{rule_id}")
def delete_market_rule(rule_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    return {"deleted": rule_id}


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
def create_route_rule(body: RouteRuleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = RouteKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    return rule


@router.patch("/route/{rule_id}", response_model=RouteRuleOut)
def update_route_rule(rule_id: int, body: RouteRuleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_classification_cache()
    return rule


@router.delete("/route/{rule_id}")
def delete_route_rule(rule_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    db.delete(rule)
    db.commit()
    invalidate_classification_cache()
    return {"deleted": rule_id}


@router.post("/seed-market-defaults")
def seed_market_defaults(_: User = Depends(require_admin)):
    count = seed_market_rules_from_hardcode()
    return {"imported": count, "message": f"Đã import {count} keyword mặc định" if count else "DB đã có rules"}


@router.post("/sync-route-from-sheet")
def sync_route_from_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Import quy tắc tuyến tour từ Google Sheet 'Điểm tuyến Tour'."""
    from scrapers.route_rules import load_route_rules

    raw = load_route_rules()
    db.query(RouteKeywordRule).delete()
    count = 0
    order = 0
    for market, rule_list in raw.items():
        for rule in rule_list:
            kws = ", ".join(rule.get("keywords", []))
            if not kws:
                continue
            db.add(RouteKeywordRule(
                thi_truong=market,
                tuyen_tour=rule.get("route", market),
                keywords=kws,
                sort_order=order,
            ))
            count += 1
            order += 1
    db.commit()
    invalidate_classification_cache()
    return {"imported": count}
