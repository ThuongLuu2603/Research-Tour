"""Phân tích thị trường — giá & tần suất KH có trọng số theo số đoàn."""
from __future__ import annotations

from collections import defaultdict

from compare_engine import deduplicate_tours, is_vietravel, parse_duration_days
from departure_parser import parse_departure_frequency
from models import Tour


def _weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return round(sum(v for v, _ in pairs) / len(pairs), 0)
    return round(sum(v * w for v, w in pairs) / total_w, 0)


def _tour_metrics(t: Tour) -> dict | None:
    gia = t.gia or 0
    days = parse_duration_days(t.thoi_gian, t.so_ngay)
    if gia <= 0 or not days:
        return None
    freq = parse_departure_frequency(t.lich_kh)["monthly_estimate"]
    return {
        "gia": gia,
        "days": days,
        "price_day": gia / days,
        "freq": freq,
        "cong_ty": t.cong_ty or "",
        "thi_truong": t.thi_truong or "Khác",
        "tuyen_tour": t.tuyen_tour or "",
        "is_vietravel": is_vietravel(t.cong_ty),
    }


def _aggregate_bucket(items: list[dict]) -> dict:
    if not items:
        return {
            "tour_count": 0,
            "departure_monthly": 0.0,
            "avg_price": None,
            "avg_days": None,
            "avg_price_day": None,
            "market_price": None,
        }
    freq_total = sum(i["freq"] for i in items)
    avg_price = _weighted_avg([(i["gia"], i["freq"]) for i in items])
    avg_days = _weighted_avg([(i["days"], i["freq"]) for i in items])
    avg_day = _weighted_avg([(i["price_day"], i["freq"]) for i in items])
    market_price = round(avg_day * avg_days, 0) if avg_day and avg_days else None
    return {
        "tour_count": len(items),
        "departure_monthly": round(freq_total, 1),
        "avg_price": avg_price,
        "avg_days": round(avg_days, 1) if avg_days else None,
        "avg_price_day": avg_day,
        "market_price": market_price,
    }


def build_market_intelligence(tours: list[Tour]) -> dict:
    tours = deduplicate_tours(tours)
    metrics: list[dict] = []
    for t in tours:
        m = _tour_metrics(t)
        if m:
            metrics.append(m)

    by_market: dict[str, list[dict]] = defaultdict(list)
    by_company: dict[str, list[dict]] = defaultdict(list)
    by_market_company: dict[tuple[str, str], list[dict]] = defaultdict(list)
    by_route: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for m in metrics:
        mk = m["thi_truong"]
        by_market[mk].append(m)
        by_company[m["cong_ty"]].append(m)
        by_market_company[(mk, m["cong_ty"])].append(m)
        if m["tuyen_tour"]:
            by_route[(mk, m["tuyen_tour"])].append(m)

    total_departures = sum(x["freq"] for x in metrics)
    total_tours = len(metrics)

    markets = []
    for label, items in sorted(by_market.items(), key=lambda x: -sum(i["freq"] for i in x[1])):
        agg = _aggregate_bucket(items)
        markets.append({
            "label": label,
            **agg,
            "departure_share_pct": round(agg["departure_monthly"] / total_departures * 100, 1) if total_departures else 0,
            "tour_share_pct": round(len(items) / total_tours * 100, 1) if total_tours else 0,
        })

    companies = []
    for label, items in sorted(by_company.items(), key=lambda x: -sum(i["freq"] for i in x[1])):
        if not label:
            continue
        agg = _aggregate_bucket(items)
        companies.append({
            "label": label,
            **agg,
            "departure_share_pct": round(agg["departure_monthly"] / total_departures * 100, 1) if total_departures else 0,
            "is_vietravel": items[0]["is_vietravel"],
        })

    routes = []
    for (market, route), items in sorted(by_route.items(), key=lambda x: -sum(i["freq"] for i in x[1])):
        agg = _aggregate_bucket(items)
        routes.append({
            "thi_truong": market,
            "tuyen_tour": route,
            **agg,
        })

    vtr_items = [m for m in metrics if m["is_vietravel"]]
    mkt_items = [m for m in metrics if not m["is_vietravel"]]
    vtr_agg = _aggregate_bucket(vtr_items)
    mkt_agg = _aggregate_bucket(mkt_items)

    return {
        "methodology": (
            "Mỗi tour có thể có nhiều ngày/đoàn KH — ước tính lượt KH/tháng từ lịch khởi hành làm trọng số. "
            "Giá TB = Σ(giá × trọng số) ÷ Σ(trọng số). "
            "Giá thị trường (tuyến) = Giá TB ngày × Số ngày TB. "
            "Thị phần đoàn = % lượt KH/tháng so với toàn hệ thống."
        ),
        "totals": {
            "tours": total_tours,
            "departure_monthly": round(total_departures, 1),
            "markets": len(markets),
            "companies": len(companies),
        },
        "vietravel": vtr_agg,
        "market_avg": mkt_agg,
        "markets": markets[:40],
        "companies": companies[:30],
        "routes": routes[:50],
    }
