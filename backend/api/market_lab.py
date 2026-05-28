"""Tour Market Lab API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_current_user
from database import get_db
from market_lab_engine import get_market_lab_overview, get_supply_calendar
from models import User

router = APIRouter(prefix="/api/market-lab", tags=["market-lab"])


@router.get("/overview")
def overview(
    grain: str = Query("route", pattern="^(route|market)$"),
    tab: str = Query("opportunity", pattern="^(opportunity|operating)$"),
    thi_truong: str | None = Query(None),
    hide_suspect: bool = Query(True),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return get_market_lab_overview(
        db, grain=grain, tab=tab, thi_truong=thi_truong or None, hide_suspect=hide_suspect,
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
    data = get_market_lab_overview(db, grain="route", tab="opportunity", thi_truong=thi_truong or None)
    return data.get("weekly_brief", {})
