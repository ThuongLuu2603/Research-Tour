from __future__ import annotations

from sqlalchemy import func, case
from sqlalchemy.orm import Session, load_only
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel

from api.auth import get_current_user
from data_sources import MIN_VALID_PRICE
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

_ANALYTICS_CACHE_SEC = 300  # 5 phút — dữ liệu thay đổi theo batch, không realtime

SEGMENT_ORDER = ["Standard", "Premium", "Luxury", "Chưa có giá"]


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
    median_gia: float | None = None
    avg_price_day: float | None = None
    avg_departures_per_month: float | None = None
    count: int


class TreemapNode(BaseModel):
    id: str
    parent: str
    value: int
    label: str


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/kpi", response_model=KPIResponse)
def kpi(
    response: Response,
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_ANALYTICS_CACHE_SEC}"
    q = db.query(Tour)
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))

    # 1 query thay vì 5 queries riêng lẻ
    row = q.with_entities(
        func.count(Tour.id).label("total"),
        func.count(func.distinct(Tour.cong_ty)).label("companies"),
        func.count(func.distinct(Tour.thi_truong)).label("markets"),
        func.count(func.distinct(Tour.tuyen_tour)).label("routes"),
        func.max(Tour.updated_at).label("last_at"),
    ).one()

    last_updated = row.last_at.strftime("%d/%m/%Y %H:%M") if row.last_at else None
    return KPIResponse(
        total_tours=row.total or 0,
        total_companies=row.companies or 0,
        total_markets=row.markets or 0,
        total_routes=row.routes or 0,
        last_updated=last_updated,
    )


@router.get("/by-market", response_model=list[BarItem])
def by_market(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from tour_filters import market_filter_clause
    q = db.query(Tour.thi_truong, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.thi_truong != "")
        .filter(market_filter_clause(Tour))
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
    from tour_filters import market_filter_clause
    q = db.query(Tour.cong_ty, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.cong_ty != "")
        .filter(market_filter_clause(Tour))
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
    from tour_filters import market_filter_clause
    q = db.query(Tour.phan_khuc, func.count(Tour.id).label("cnt"))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.phan_khuc != "")
        .filter(market_filter_clause(Tour))
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
    response: Response,
    nguon: list[str] = Query([]),
    limit: int = Query(2000, ge=100, le=5000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_ANALYTICS_CACHE_SEC}"
    q = db.query(Tour.ten_tour, Tour.cong_ty, Tour.thi_truong, Tour.gia, Tour.so_ngay)
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    rows = (
        q.filter(Tour.gia != None, Tour.so_ngay != None, Tour.so_ngay > 0, Tour.so_ngay <= 45)
        .order_by(Tour.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [
        ScatterPoint(
            ten_tour=r.ten_tour,
            cong_ty=r.cong_ty,
            thi_truong=r.thi_truong,
            gia=r.gia,
            so_ngay=r.so_ngay,
        )
        for r in rows
    ]


@router.get("/price-stats", response_model=list[PriceStatsItem])
def price_stats(
    response: Response,
    group_by: str = Query("thi_truong"),
    nguon: list[str] = Query([]),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from market_analytics import build_price_analysis

    from tour_sources import apply_analytics_tour_filters

    response.headers["Cache-Control"] = f"private, max-age={_ANALYTICS_CACHE_SEC}"
    q = (
        db.query(Tour)
        .options(load_only(
            Tour.id,
            Tour.ten_tour,
            Tour.ma_tour,
            Tour.link_url,
            Tour.updated_at,
            Tour.cong_ty,
            Tour.thi_truong,
            Tour.tuyen_tour,
            Tour.thoi_gian,
            Tour.so_ngay,
            Tour.gia,
            Tour.lich_kh,
            Tour.nguon,
            Tour.sheet_source,
        ))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
    )
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    else:
        q = apply_analytics_tour_filters(q)
    rows = build_price_analysis(q.all(), group_by)[:limit]
    return [PriceStatsItem(**r) for r in rows]


@router.get("/treemap", response_model=list[TreemapNode])
def treemap(
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from tour_sources import apply_market_compare_source_filter

    q = db.query(
        Tour.thi_truong, Tour.cong_ty, func.count(Tour.id).label("cnt")
    )
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    else:
        q = apply_market_compare_source_filter(q)
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
    response: Response,
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from market_analytics import build_market_intelligence

    from tour_sources import apply_analytics_tour_filters, filter_tours_for_market_compare

    response.headers["Cache-Control"] = f"private, max-age={_ANALYTICS_CACHE_SEC}"
    q = (
        db.query(Tour)
        .options(load_only(
            Tour.id,
            Tour.ten_tour,
            Tour.ma_tour,
            Tour.link_url,
            Tour.updated_at,
            Tour.cong_ty,
            Tour.thi_truong,
            Tour.tuyen_tour,
            Tour.thoi_gian,
            Tour.so_ngay,
            Tour.gia,
            Tour.lich_kh,
            Tour.nguon,
            Tour.sheet_source,
        ))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
    )
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
        tours = filter_tours_for_market_compare(q.all())
    else:
        q = apply_analytics_tour_filters(q)
        tours = q.all()
    return build_market_intelligence(tours)


@router.get("/competitor/{company}", response_model=dict)
def competitor_profile(
    company: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from fastapi import HTTPException

    # 1 query: tất cả tour của công ty
    tours = (
        db.query(Tour.id, Tour.ten_tour, Tour.thi_truong, Tour.tuyen_tour, Tour.gia, Tour.gia_raw, Tour.link_url)
        .filter(Tour.cong_ty == company)
        .all()
    )
    if not tours:
        raise HTTPException(status_code=404, detail="Không tìm thấy công ty")

    prices = [r.gia for r in tours if r.gia]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    market_counts: dict[str, int] = {}
    co_route_prices: dict[str, list[float]] = {}
    for r in tours:
        if r.thi_truong:
            market_counts[r.thi_truong] = market_counts.get(r.thi_truong, 0) + 1
        if r.tuyen_tour and r.gia:
            co_route_prices.setdefault(r.tuyen_tour, []).append(r.gia)

    # 1 GROUP BY query thay vì N queries
    route_list = list(co_route_prices.keys())
    market_avgs: dict[str, float] = {}
    if route_list:
        for row in (
            db.query(Tour.tuyen_tour, func.avg(Tour.gia).label("avg_gia"))
            .filter(Tour.tuyen_tour.in_(route_list), Tour.gia != None)
            .group_by(Tour.tuyen_tour)
            .all()
        ):
            market_avgs[row.tuyen_tour] = float(row.avg_gia)

    route_avg_market: list[dict] = []
    for route, co_prices in co_route_prices.items():
        all_avg = market_avgs.get(route)
        if co_prices and all_avg:
            co_avg = sum(co_prices) / len(co_prices)
            pct = round((co_avg / all_avg - 1) * 100, 1)
            route_avg_market.append({"route": route, "co_avg": round(co_avg, 0), "market_avg": round(all_avg, 0), "diff_pct": pct})

    return {
        "company": company,
        "total_tours": len(tours),
        "avg_price": avg_price,
        "markets": [{"label": k, "value": v} for k, v in sorted(market_counts.items(), key=lambda x: -x[1])],
        "route_positioning": sorted(route_avg_market, key=lambda x: abs(x["diff_pct"]), reverse=True)[:15],
        "tours": [{"id": r.id, "ten_tour": r.ten_tour, "thi_truong": r.thi_truong, "tuyen_tour": r.tuyen_tour, "gia_raw": r.gia_raw, "gia": r.gia, "link_url": r.link_url} for r in tours[:50]],
    }
