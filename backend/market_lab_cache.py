"""Cache Market Lab — tái dùng compare context, tránh tính segment mỗi request."""
from __future__ import annotations

import logging
import threading
import time
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from compare_cache import get_compare_context
from market_lab_engine import RouteAgg, build_route_aggregates_from_context
from models import RouteDailyMetrics

logger = logging.getLogger(__name__)

TTL_SECONDS = 180
_lock = threading.Lock()
_cache: tuple[float, dict[str, RouteAgg]] | None = None
_inflight: threading.Event | None = None


def get_cached_routes(db: Session, *, force: bool = False) -> dict[str, RouteAgg]:
    global _cache, _inflight
    now = time.time()

    with _lock:
        if not force and _cache and now - _cache[0] < TTL_SECONDS:
            return _cache[1]
        if _inflight is not None:
            waiter = _inflight
            is_owner = False
        else:
            waiter = threading.Event()
            _inflight = waiter
            is_owner = True

    if not is_owner:
        waiter.wait(timeout=300)
        with _lock:
            if _cache:
                return _cache[1]
        return get_cached_routes(db, force=True)

    t0 = time.time()
    try:
        ctx = get_compare_context(db, [], "", "")
        routes = build_route_aggregates_from_context(
            ctx.segments, ctx.tours, include_supply_months=False,
        )
        with _lock:
            _cache = (time.time(), routes)
        logger.info("Market Lab cache: %s routes in %.1fs", len(routes), time.time() - t0)
        return routes
    finally:
        with _lock:
            ev = _inflight
            _inflight = None
            if ev:
                ev.set()


def invalidate_market_lab_cache() -> None:
    global _cache, _inflight
    with _lock:
        _cache = None
        if _inflight:
            _inflight.set()
            _inflight = None


def prewarm_market_lab_cache(db: Session) -> None:
    try:
        get_cached_routes(db, force=True)
    except Exception as e:
        logger.warning("Market Lab prewarm failed: %s", e)


def load_momentum_map(db: Session) -> dict[str, dict]:
    """Momentum mọi tuyến — tối đa 2 ngày snapshot, 1 query."""
    history_days = db.query(func.count(func.distinct(RouteDailyMetrics.snapshot_date))).scalar() or 0
    dates = [
        r[0]
        for r in db.query(RouteDailyMetrics.snapshot_date)
        .distinct()
        .order_by(RouteDailyMetrics.snapshot_date.desc())
        .limit(2)
        .all()
    ]
    if not dates:
        return {}

    rows = db.query(RouteDailyMetrics).filter(RouteDailyMetrics.snapshot_date.in_(dates)).all()
    by_key: dict[str, list[RouteDailyMetrics]] = {}
    for row in rows:
        by_key.setdefault(row.route_key, []).append(row)

    empty = {"history_days": history_days, "supply_delta_pct": None, "gap_delta": None}
    out: dict[str, dict] = {}

    def pct_delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / abs(b) * 100, 1)

    for rk, snaps in by_key.items():
        snaps.sort(key=lambda x: x.snapshot_date, reverse=True)
        if len(snaps) < 2:
            out[rk] = {**empty}
            continue
        cur, prev = snaps[0], snaps[1]
        out[rk] = {
            "history_days": history_days,
            "supply_delta_pct": pct_delta(cur.market_departures_monthly, prev.market_departures_monthly),
            "vtr_supply_delta_pct": pct_delta(cur.vtr_departures_monthly, prev.vtr_departures_monthly),
            "gap_delta": (
                round(cur.avg_gap_pct - prev.avg_gap_pct, 1)
                if cur.avg_gap_pct is not None and prev.avg_gap_pct is not None
                else None
            ),
        }
    return out


def routes_from_daily_metrics(db: Session, snap_date: date | None = None) -> dict[str, RouteAgg] | None:
    if snap_date is None:
        snap_date = (
            db.query(RouteDailyMetrics.snapshot_date)
            .order_by(RouteDailyMetrics.snapshot_date.desc())
            .limit(1)
            .scalar()
        )
    if not snap_date:
        return None

    rows = db.query(RouteDailyMetrics).filter(RouteDailyMetrics.snapshot_date == snap_date).all()
    if len(rows) < 5:
        return None

    routes: dict[str, RouteAgg] = {}
    for r in rows:
        routes[r.route_key] = RouteAgg(
            route_key=r.route_key,
            thi_truong=r.thi_truong,
            tuyen_tour=r.tuyen_tour,
            vtr_tour_count=r.vtr_tour_count,
            market_tour_count=r.market_tour_count,
            market_departures_monthly=r.market_departures_monthly,
            vtr_departures_monthly=r.vtr_departures_monthly,
            avg_gap_pct=r.avg_gap_pct,
            avg_freq_gap_pct=r.freq_gap_pct,
            market_price_day=r.market_price_day,
            phase=r.phase or "stable",
            opportunity_score=r.opportunity_score,
            competitor_count=r.competitor_count,
        )
    return routes
