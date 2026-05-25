from __future__ import annotations

from sqlalchemy import func, case
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.auth import get_current_user
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

SEGMENT_ORDER = ["Budget (< 2tr)", "Mid (2–5tr)", "Premium (5–15tr)", "Luxury (> 15tr)", "Chưa có giá"]


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class KPIResponse(BaseModel):
    total_tours: int
    total_companies: int
    total_markets: int
    total_routes: int
    last_updated: str | None


class BarItem(BaseModel):
    label: str
    value: int | float


class ScatterPoint(BaseModel):
    ten_tour: str
    cong_ty: str
    thi_truong: str
    gia: float
    so_ngay: float


class PriceStatsItem(BaseModel):
    group: str
    min_gia: float | None
    max_gia: float | None
    avg_gia: float | None
    count: int


class TreemapNode(BaseModel):
    id: str
    parent: str
    value: int
    label: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/kpi", response_model=KPIResponse)
def kpi(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour)
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))

    total_tours = q.count()
    total_companies = q.with_entities(func.count(func.distinct(Tour.cong_ty))).scalar() or 0
    total_markets = q.with_entities(func.count(func.distinct(Tour.thi_truong))).scalar() or 0
    total_routes = q.with_entities(func.count(func.distinct(Tour.tuyen_tour))).scalar() or 0

    last = q.order_by(Tour.updated_at.desc()).first()
    last_updated = last.updated_at.strftime("%d/%m/%Y %H:%M") if last else None

    return KPIResponse(
        total_tours=total_tours,
        total_companies=total_companies,
        total_markets=total_markets,
        total_routes=total_routes,
        last_updated=last_updated,
    )


@router.get("/by-market", response_model=list[BarItem])
def by_market(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour.thi_truong, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.thi_truong != "")
        .group_by(Tour.thi_truong)
        .order_by(func.count(Tour.id).desc())
        .all()
    )
    return [BarItem(label=r.thi_truong, value=r.cnt) for r in rows]


@router.get("/by-company", response_model=list[BarItem])
def by_company(
    limit: int = Query(15, ge=1, le=50),
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour.cong_ty, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.cong_ty != "")
        .group_by(Tour.cong_ty)
        .order_by(func.count(Tour.id).desc())
        .limit(limit)
        .all()
    )
    return [BarItem(label=r.cong_ty, value=r.cnt) for r in rows]


@router.get("/by-segment", response_model=list[BarItem])
def by_segment(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour.phan_khuc, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.phan_khuc != "")
        .group_by(Tour.phan_khuc)
        .all()
    )
    mapping = {r.phan_khuc: r.cnt for r in rows}
    return [
        BarItem(label=seg, value=mapping.get(seg, 0))
        for seg in SEGMENT_ORDER
        if seg in mapping
    ]


@router.get("/scatter", response_model=list[ScatterPoint])
def scatter(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour)
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    tours = (
        q.filter(Tour.gia != None, Tour.so_ngay != None, Tour.so_ngay > 0, Tour.so_ngay <= 45)
        .all()
    )
    return [
        ScatterPoint(
            ten_tour=t.ten_tour,
            cong_ty=t.cong_ty,
            thi_truong=t.thi_truong,
            gia=t.gia,
            so_ngay=t.so_ngay,
        )
        for t in tours
    ]


@router.get("/price-stats", response_model=list[PriceStatsItem])
def price_stats(
    group_by: str = Query("thi_truong"),
    nguon: list[str] = Query([]),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    col_map = {
        "thi_truong": Tour.thi_truong,
        "cong_ty": Tour.cong_ty,
        "tuyen_tour": Tour.tuyen_tour,
    }
    col = col_map.get(group_by, Tour.thi_truong)
    q = db.query(
        col.label("group"),
        func.min(Tour.gia).label("min_gia"),
        func.max(Tour.gia).label("max_gia"),
        func.avg(Tour.gia).label("avg_gia"),
        func.count(Tour.id).label("cnt"),
    )
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.gia != None, col != "")
        .group_by(col)
        .order_by(func.count(Tour.id).desc())
        .limit(limit)
        .all()
    )
    return [
        PriceStatsItem(
            group=r.group,
            min_gia=r.min_gia,
            max_gia=r.max_gia,
            avg_gia=round(r.avg_gia, 0) if r.avg_gia else None,
            count=r.cnt,
        )
        for r in rows
    ]


@router.get("/treemap", response_model=list[TreemapNode])
def treemap(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(
        Tour.thi_truong, Tour.cong_ty, func.count(Tour.id).label("cnt")
    )
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.thi_truong != "", Tour.cong_ty != "")
        .group_by(Tour.thi_truong, Tour.cong_ty)
        .all()
    )

    market_totals: dict[str, int] = {}
    for r in rows:
        market_totals[r.thi_truong] = market_totals.get(r.thi_truong, 0) + r.cnt

    nodes: list[TreemapNode] = [TreemapNode(id="root", parent="", value=0, label="Tất cả")]
    for market, total in market_totals.items():
        nodes.append(TreemapNode(id=market, parent="root", value=total, label=market))
    for r in rows:
        node_id = f"{r.thi_truong}/{r.cong_ty}"
        nodes.append(TreemapNode(id=node_id, parent=r.thi_truong, value=r.cnt, label=r.cong_ty))
    return nodes


@router.get("/market-intelligence")
def market_intelligence(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from market_analytics import build_market_intelligence

    q = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    return build_market_intelligence(q.all())


@router.get("/competitor/{company}", response_model=dict)
def competitor_profile(
    company: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = db.query(Tour).filter(Tour.cong_ty == company).all()
    if not tours:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Không tìm thấy công ty")

    prices = [t.gia for t in tours if t.gia]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    market_counts: dict[str, int] = {}
    for t in tours:
        if t.thi_truong:
            market_counts[t.thi_truong] = market_counts.get(t.thi_truong, 0) + 1

    route_avg_market: list[dict] = []
    for route in set(t.tuyen_tour for t in tours if t.tuyen_tour):
        co_prices = [t.gia for t in tours if t.tuyen_tour == route and t.gia]
        all_prices_q = (
            db.query(func.avg(Tour.gia))
            .filter(Tour.tuyen_tour == route, Tour.gia != None)
            .scalar()
        )
        if co_prices and all_prices_q:
            co_avg = sum(co_prices) / len(co_prices)
            pct = round((co_avg / all_prices_q - 1) * 100, 1)
            route_avg_market.append({"route": route, "co_avg": round(co_avg, 0), "market_avg": round(all_prices_q, 0), "diff_pct": pct})

    return {
        "company": company,
        "total_tours": len(tours),
        "avg_price": avg_price,
        "markets": [{"label": k, "value": v} for k, v in sorted(market_counts.items(), key=lambda x: -x[1])],
        "route_positioning": sorted(route_avg_market, key=lambda x: abs(x["diff_pct"]), reverse=True)[:15],
        "tours": [{"id": t.id, "ten_tour": t.ten_tour, "thi_truong": t.thi_truong, "tuyen_tour": t.tuyen_tour, "gia_raw": t.gia_raw, "gia": t.gia, "link_url": t.link_url} for t in tours[:50]],
    }
