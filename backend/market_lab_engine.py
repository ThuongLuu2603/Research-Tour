"""Tour Market Lab — intelligence theo Tuyến tour (không dùng KS/HK)."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from compare_engine import build_segment_stats, deduplicate_tours, is_vietravel, route_for_segment
from tour_sources import apply_market_compare_source_filter
from departure_parser import parse_departure_dates, parse_departure_frequency
from models import IntelAlert, RouteDailyMetrics, Tour


def make_route_key(thi_truong: str, tuyen_tour: str) -> str:
    return f"{(thi_truong or '').strip()}|{(tuyen_tour or '').strip()}"


def parse_route_key(key: str) -> tuple[str, str]:
    if "|" not in key:
        return key, ""
    a, b = key.split("|", 1)
    return a, b


def _month_key(d: datetime) -> str:
    return f"{d.year}-{d.month:02d}"


def _slots_by_month_from_tours(tours: list[Tour], *, vtr_only: bool | None = None) -> dict[str, float]:
    """Tổng slot KH/tháng theo tháng khởi hành (ước tính từ lich_kh)."""
    buckets: dict[str, float] = defaultdict(float)
    for t in tours:
        is_v = is_vietravel(t.cong_ty)
        if vtr_only is True and not is_v:
            continue
        if vtr_only is False and is_v:
            continue
        freq = parse_departure_frequency(t.lich_kh)["monthly_estimate"]
        dates = parse_departure_dates(t.lich_kh)
        if dates:
            months = {_month_key(d) for d in dates}
            share = freq / max(len(months), 1)
            for mk in months:
                buckets[mk] += share
        else:
            mk = _month_key(datetime.utcnow())
            buckets[mk] += freq
    return dict(buckets)


@dataclass
class RouteAgg:
    route_key: str
    thi_truong: str
    tuyen_tour: str
    vtr_tour_count: int = 0
    market_tour_count: int = 0
    market_departures_monthly: float = 0.0
    vtr_departures_monthly: float = 0.0
    avg_gap_pct: float | None = None
    avg_freq_gap_pct: float | None = None
    market_price_day: float | None = None
    phase: str = "stable"
    opportunity_score: float = 0.0
    competitor_count: int = 0
    market_slots_by_month: dict[str, float] = field(default_factory=dict)
    vtr_slots_by_month: dict[str, float] = field(default_factory=dict)
    gap_sum: float = 0.0
    gap_weight: float = 0.0
    freq_gap_sum: float = 0.0
    freq_gap_weight: float = 0.0

    quality: str = "ok"
    quality_note: str = ""
    dominant_market: str | None = None

    def to_dict(self, *, momentum: dict | None = None) -> dict:
        return {
            "route_key": self.route_key,
            "thi_truong": self.thi_truong,
            "tuyen_tour": self.tuyen_tour,
            "quality": self.quality,
            "quality_note": self.quality_note,
            "dominant_market": self.dominant_market,
            "vtr_tour_count": self.vtr_tour_count,
            "market_tour_count": self.market_tour_count,
            "market_departures_monthly": round(self.market_departures_monthly, 1),
            "vtr_departures_monthly": round(self.vtr_departures_monthly, 1),
            "avg_gap_pct": self.avg_gap_pct,
            "avg_freq_gap_pct": self.avg_freq_gap_pct,
            "market_price_day": self.market_price_day,
            "phase": self.phase,
            "opportunity_score": round(self.opportunity_score, 1),
            "competitor_count": self.competitor_count,
            "momentum": momentum or {},
        }


def _classify_phase(
    supply_delta: float | None,
    price_delta: float | None,
    freq_gap: float | None,
) -> str:
    if supply_delta is not None and supply_delta >= 12 and (price_delta is None or price_delta > -2):
        return "expansion"
    if price_delta is not None and price_delta <= -3 and (supply_delta is None or supply_delta >= 0):
        return "price_war"
    if supply_delta is not None and supply_delta <= -10:
        return "tight_supply"
    if freq_gap is not None and freq_gap <= -25:
        return "freq_pressure"
    return "stable"


def build_route_aggregates_from_context(
    segments,
    tours: list[Tour],
    *,
    include_supply_months: bool = True,
) -> dict[str, RouteAgg]:
    routes: dict[str, RouteAgg] = {}
    companies_by_route: dict[str, set[str]] = defaultdict(set)

    for t in tours:
        market = (t.thi_truong or "").strip() or "Khác"
        route = route_for_segment(t)
        if not route or not t.gia or t.gia <= 0:
            continue
        rk = make_route_key(market, route)
        if rk not in routes:
            routes[rk] = RouteAgg(route_key=rk, thi_truong=market, tuyen_tour=route)
        agg = routes[rk]
        if is_vietravel(t.cong_ty):
            agg.vtr_tour_count += 1
        else:
            agg.market_tour_count += 1
            if t.cong_ty:
                companies_by_route[rk].add(t.cong_ty.strip())

    for s in segments:
        rk = make_route_key(s.thi_truong, s.tuyen_tour)
        if rk not in routes:
            routes[rk] = RouteAgg(
                route_key=rk, thi_truong=s.thi_truong, tuyen_tour=s.tuyen_tour,
            )
        agg = routes[rk]
        w = max(s.market_freq_monthly, 1.0)
        agg.market_departures_monthly += s.market_freq_monthly
        agg.vtr_departures_monthly += s.vtr_freq_monthly
        if s.gap_pct is not None and s.vtr_entries:
            agg.gap_sum += s.gap_pct * w
            agg.gap_weight += w
        if s.freq_gap_pct is not None and s.vtr_entries:
            agg.freq_gap_sum += s.freq_gap_pct * w
            agg.freq_gap_weight += w
        if s.market_avg_day:
            if agg.market_price_day is None:
                agg.market_price_day = s.market_avg_day
            else:
                agg.market_price_day = (agg.market_price_day + s.market_avg_day) / 2

    route_tours: dict[str, list[Tour]] = defaultdict(list)
    if include_supply_months:
        for t in tours:
            market = (t.thi_truong or "").strip() or "Khác"
            route = route_for_segment(t)
            if route and t.gia and t.gia > 0:
                route_tours[make_route_key(market, route)].append(t)

    for rk, agg in routes.items():
        if include_supply_months:
            rt = route_tours.get(rk, [])
            agg.market_slots_by_month = _slots_by_month_from_tours(rt, vtr_only=False)
            agg.vtr_slots_by_month = _slots_by_month_from_tours(rt, vtr_only=True)
        agg.competitor_count = len(companies_by_route.get(rk, set()))
        if agg.gap_weight > 0:
            agg.avg_gap_pct = round(agg.gap_sum / agg.gap_weight, 1)
        if agg.freq_gap_weight > 0:
            agg.avg_freq_gap_pct = round(agg.freq_gap_sum / agg.freq_gap_weight, 1)

        mkt_dep = agg.market_departures_monthly
        vtr_dep = agg.vtr_departures_monthly
        if agg.vtr_tour_count == 0 and mkt_dep >= 8:
            agg.opportunity_score = mkt_dep * (1 + agg.competitor_count * 0.15)
        elif agg.vtr_tour_count > 0 and (agg.avg_freq_gap_pct or 0) <= -20:
            agg.opportunity_score = abs(agg.avg_freq_gap_pct or 0) * mkt_dep / 10
        agg.phase = _classify_phase(None, None, agg.avg_freq_gap_pct)

    return routes


def build_route_aggregates(tours: list[Tour], *, include_supply_months: bool = True) -> dict[str, RouteAgg]:
    tours = deduplicate_tours(tours)
    segments = build_segment_stats(tours, dedup=False)
    return build_route_aggregates_from_context(
        segments, tours, include_supply_months=include_supply_months,
    )


def rollup_markets(routes: dict[str, RouteAgg]) -> list[dict]:
    by_market: dict[str, list[RouteAgg]] = defaultdict(list)
    for r in routes.values():
        by_market[r.thi_truong].append(r)

    out: list[dict] = []
    for market, items in by_market.items():
        mkt_dep = sum(i.market_departures_monthly for i in items)
        vtr_dep = sum(i.vtr_departures_monthly for i in items)
        gaps = [i.avg_gap_pct for i in items if i.avg_gap_pct is not None and i.vtr_tour_count > 0]
        avg_gap = round(sum(gaps) / len(gaps), 1) if gaps else None
        white = sum(1 for i in items if i.vtr_tour_count == 0 and i.market_departures_monthly >= 8)
        out.append({
            "thi_truong": market,
            "route_count": len(items),
            "market_departures_monthly": round(mkt_dep, 1),
            "vtr_departures_monthly": round(vtr_dep, 1),
            "avg_gap_pct": avg_gap,
            "white_space_routes": white,
            "opportunity_score": round(sum(i.opportunity_score for i in items), 1),
        })
    out.sort(key=lambda x: -x["opportunity_score"])
    return out


def capture_route_daily_metrics(db: Session, tours: list[Tour] | None = None) -> int:
    from market_lab_cache import get_cached_routes, invalidate_market_lab_cache

    snap_date = date.today()
    db.query(RouteDailyMetrics).filter(RouteDailyMetrics.snapshot_date == snap_date).delete()
    if tours is None:
        routes = get_cached_routes(db, force=True)
    else:
        routes = build_route_aggregates(tours, include_supply_months=False)
    invalidate_market_lab_cache()
    for agg in routes.values():
        db.add(RouteDailyMetrics(
            snapshot_date=snap_date,
            route_key=agg.route_key,
            thi_truong=agg.thi_truong,
            tuyen_tour=agg.tuyen_tour,
            vtr_tour_count=agg.vtr_tour_count,
            market_tour_count=agg.market_tour_count,
            market_departures_monthly=agg.market_departures_monthly,
            vtr_departures_monthly=agg.vtr_departures_monthly,
            avg_gap_pct=agg.avg_gap_pct,
            freq_gap_pct=agg.avg_freq_gap_pct,
            market_price_day=agg.market_price_day,
            phase=agg.phase,
            opportunity_score=agg.opportunity_score,
            competitor_count=agg.competitor_count,
            market_slots_json=json.dumps(agg.market_slots_by_month, ensure_ascii=False),
            vtr_slots_json=json.dumps(agg.vtr_slots_by_month, ensure_ascii=False),
            created_at=datetime.utcnow(),
        ))
    db.commit()
    return len(routes)


def _route_momentum(db: Session, route_key: str) -> dict:
    rows = (
        db.query(RouteDailyMetrics)
        .filter(RouteDailyMetrics.route_key == route_key)
        .order_by(RouteDailyMetrics.snapshot_date.desc())
        .limit(2)
        .all()
    )
    if len(rows) < 2:
        return {"history_days": len(rows), "supply_delta_pct": None, "price_day_delta_pct": None}
    cur, prev = rows[0], rows[1]

    def pct_delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / abs(b) * 100, 1)

    return {
        "history_days": db.query(func.count(func.distinct(RouteDailyMetrics.snapshot_date))).scalar() or 0,
        "supply_delta_pct": pct_delta(cur.market_departures_monthly, prev.market_departures_monthly),
        "vtr_supply_delta_pct": pct_delta(cur.vtr_departures_monthly, prev.vtr_departures_monthly),
        "gap_delta": (
            round(cur.avg_gap_pct - prev.avg_gap_pct, 1)
            if cur.avg_gap_pct is not None and prev.avg_gap_pct is not None
            else None
        ),
    }


def build_weekly_brief(
    routes: dict[str, RouteAgg],
    db: Session,
    momentum_map: dict[str, dict] | None = None,
) -> dict:
    """Dự báo / kịch bản 1 tuần — theo top tuyến."""
    if momentum_map is None:
        from market_lab_cache import load_momentum_map
        momentum_map = load_momentum_map(db)

    scored: list[tuple[float, RouteAgg]] = []
    for r in routes.values():
        mom = momentum_map.get(r.route_key, {})
        score = r.opportunity_score + abs(mom.get("supply_delta_pct") or 0) * 2
        if r.vtr_tour_count > 0:
            score += r.market_departures_monthly * 0.1
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    top = [r for _, r in scored[:5]]

    scenarios = []
    for r in top:
        mom = momentum_map.get(r.route_key, {})
        supply_d = mom.get("supply_delta_pct")
        gap_d = mom.get("gap_delta")
        if supply_d is not None and supply_d >= 10:
            base = f"TT tiếp tục mở rộng cung (~{supply_d:+.0f}% đoàn/tuần gần đây)."
            risk = "Cung ép — cân nhắc thêm lịch KH trước khi hạ giá."
        elif r.avg_gap_pct is not None and r.avg_gap_pct >= 10:
            base = f"VTR premium {r.avg_gap_pct}% — theo dõi đối thủ hạ giá."
            risk = "Giá ép — xem tour mẫu đối thủ trên web trước khi chỉnh giá."
        elif r.vtr_tour_count == 0:
            base = f"Khoảng trống: TT ~{r.market_departures_monthly:.0f} đoàn/tháng, chưa có SP VTR."
            risk = "Cơ hội mở sản phẩm mới trên tuyến này."
        else:
            base = "Ổn định — duy trì theo dõi segment chính."
            risk = "Theo dõi biến động tuần sau."

        scenarios.append({
            "route_key": r.route_key,
            "thi_truong": r.thi_truong,
            "tuyen_tour": r.tuyen_tour,
            "base": base,
            "action_hint": risk,
            "momentum": mom,
            "phase": r.phase,
            "avg_gap_pct": r.avg_gap_pct,
            "freq_gap_pct": r.avg_freq_gap_pct,
        })

    return {
        "horizon_days": 7,
        "generated_at": datetime.utcnow().isoformat(),
        "top_routes": scenarios,
        "note": "Dự báo rule-based từ snapshot hàng ngày; độ tin cậy tăng sau ≥7 ngày dữ liệu.",
    }


def generate_route_alerts(db: Session, routes: dict[str, RouteAgg]) -> None:
    from market_lab_cache import load_momentum_map

    since = datetime.utcnow() - timedelta(days=1)
    db.query(IntelAlert).filter(
        IntelAlert.created_at >= since,
        IntelAlert.alert_type.like("route_%"),
    ).delete()

    momentum_map = load_momentum_map(db)
    for rk, r in routes.items():
        mom = momentum_map.get(rk, {})
        supply_d = mom.get("supply_delta_pct")
        link = f"/market-lab?route={rk}"

        if r.vtr_tour_count == 0 and r.market_departures_monthly >= 15:
            db.add(IntelAlert(
                alert_type="route_white_space",
                severity="info",
                category="market_lab",
                title=f"Cơ hội tuyến: {r.tuyen_tour}",
                message=f"{r.thi_truong} · TT ~{r.market_departures_monthly:.0f} đoàn/tháng · {r.competitor_count} đối thủ",
                link_path=link,
                payload_json=json.dumps({"route_key": rk}, ensure_ascii=False),
            ))
        elif r.vtr_tour_count > 0 and r.avg_freq_gap_pct is not None and r.avg_freq_gap_pct <= -25:
            db.add(IntelAlert(
                alert_type="route_freq_risk",
                severity="warning",
                category="market_lab",
                title=f"Thiếu lịch KH: {r.tuyen_tour}",
                message=f"{r.thi_truong} · Gap tần suất {r.avg_freq_gap_pct}% vs TT",
                link_path=link,
            ))
        elif supply_d is not None and supply_d >= 15:
            db.add(IntelAlert(
                alert_type="route_supply_surge",
                severity="warning",
                category="market_lab",
                title=f"TT tăng cung: {r.tuyen_tour}",
                message=f"{r.thi_truong} · +{supply_d}% đoàn/tháng so với snapshot trước",
                link_path=link,
            ))
        elif r.avg_gap_pct is not None and r.avg_gap_pct >= 12 and (mom.get("gap_delta") or 0) >= 2:
            db.add(IntelAlert(
                alert_type="route_price_pressure",
                severity="warning",
                category="market_lab",
                title=f"Premium drift: {r.tuyen_tour}",
                message=f"Chênh giá {r.avg_gap_pct}% và đang nới thêm",
                link_path=link,
            ))

    db.commit()


def get_market_lab_overview(
    db: Session,
    *,
    grain: str = "route",
    tab: str = "opportunity",
    thi_truong: str | None = None,
    hide_suspect: bool = True,
) -> dict:
    import time
    from market_lab_cache import get_cached_routes, load_momentum_map, routes_from_daily_metrics
    from route_quality import assess_route_quality, load_tuyen_market_histogram_cached

    t0 = time.time()
    quality_hist = load_tuyen_market_histogram_cached(db)
    routes = routes_from_daily_metrics(db)
    data_source = "snapshot"
    if routes is None:
        routes = get_cached_routes(db)
        data_source = "live"

    if thi_truong:
        routes = {k: v for k, v in routes.items() if v.thi_truong == thi_truong}

    momentum_map = load_momentum_map(db)
    history_days = db.query(func.count(func.distinct(RouteDailyMetrics.snapshot_date))).scalar() or 0
    mom_default = {"history_days": history_days, "supply_delta_pct": None, "gap_delta": None}
    items: list[dict] = []
    suspect_hidden = 0
    for rk, r in routes.items():
        q = assess_route_quality(r.thi_truong, r.tuyen_tour, quality_hist)
        r.quality = q["quality"]
        r.quality_note = q.get("quality_note", "")
        r.dominant_market = q.get("dominant_market")
        if hide_suspect and q["quality"] == "market_mismatch":
            suspect_hidden += 1
            continue
        mom = momentum_map.get(rk, mom_default)
        phase = _classify_phase(
            mom.get("supply_delta_pct"),
            None,
            r.avg_freq_gap_pct,
        )
        r.phase = phase
        row = r.to_dict(momentum=mom)
        items.append(row)

    if tab == "opportunity":
        items = [i for i in items if i["vtr_tour_count"] == 0 or (i.get("avg_freq_gap_pct") or 0) <= -15]
        items.sort(key=lambda x: -x["opportunity_score"])
    else:
        items = [i for i in items if i["vtr_tour_count"] > 0]
        items.sort(key=lambda x: -x["market_departures_monthly"])

    brief = build_weekly_brief(routes, db, momentum_map)
    meta = {
        "source": data_source,
        "compute_seconds": round(time.time() - t0, 2),
        "suspect_routes_hidden": suspect_hidden,
        "hide_suspect": hide_suspect,
    }

    if grain == "market":
        return {
            "grain": "market",
            "tab": tab,
            "history_days": history_days,
            "markets": rollup_markets(routes),
            "weekly_brief": brief,
            "meta": meta,
        }

    return {
        "grain": "route",
        "tab": tab,
        "history_days": history_days,
        "routes": items[:80],
        "weekly_brief": brief,
        "markets": rollup_markets(routes)[:20],
        "meta": meta,
    }


def get_supply_calendar(db: Session, thi_truong: str, tuyen_tour: str) -> dict:
    rk = make_route_key(thi_truong, tuyen_tour)
    tours = apply_market_compare_source_filter(
        db.query(Tour).filter(
            Tour.gia != None, Tour.gia > 0, Tour.thi_truong == thi_truong  # noqa: E711
        )
    ).all()
    tours = deduplicate_tours(tours)
    matched = [
        t for t in tours
        if make_route_key((t.thi_truong or "").strip() or "Khác", route_for_segment(t)) == rk
    ]

    mkt = _slots_by_month_from_tours(matched, vtr_only=False)
    vtr = _slots_by_month_from_tours(matched, vtr_only=True)
    months = sorted(set(mkt) | set(vtr))

    rows = []
    for mk in months:
        ms = mkt.get(mk, 0)
        vs = vtr.get(mk, 0)
        rows.append({
            "month": mk,
            "market_slots": round(ms, 1),
            "vtr_slots": round(vs, 1),
            "gap_slots": round(vs - ms, 1) if vs or ms else 0,
        })

    return {
        "route_key": rk,
        "thi_truong": thi_truong,
        "tuyen_tour": tuyen_tour,
        "months": rows,
        "tour_count": len(matched),
    }
