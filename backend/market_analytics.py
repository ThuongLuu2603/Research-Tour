"""Phân tích thị trường — giá & tần suất khởi hành có trọng số theo số đoàn."""
from __future__ import annotations

from collections import defaultdict

from compare_engine import deduplicate_tours, is_vietravel, parse_duration_days
from departure_parser import parse_departure_frequency
from models import Tour
from stats_utils import robust_weighted_avg, weighted_avg, weighted_median


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
            "avg_departures_per_month": 0.0,
            "avg_price": None,
            "median_price": None,
            "avg_days": None,
            "avg_price_day": None,
            "market_price": None,
        }
    freq_total = sum(i["freq"] for i in items)
    price_pairs = [(i["gia"], i["freq"]) for i in items]
    day_pairs = [(i["days"], i["freq"]) for i in items]
    pd_pairs = [(i["price_day"], i["freq"]) for i in items]
    avg_price = robust_weighted_avg(price_pairs)
    avg_days = weighted_avg(day_pairs)
    avg_day = robust_weighted_avg(pd_pairs)
    market_price = round(avg_day * avg_days, 0) if avg_day and avg_days else None
    return {
        "tour_count": len(items),
        "departure_monthly": round(freq_total, 1),
        "avg_departures_per_month": round(freq_total / len(items), 1),
        "avg_price": avg_price,
        "median_price": weighted_median(price_pairs),
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
    by_route: dict[tuple[str, str], list[dict]] = defaultdict(list)

    for m in metrics:
        mk = m["thi_truong"]
        by_market[mk].append(m)
        by_company[m["cong_ty"]].append(m)
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
            "Mỗi Tên Tour = 1 sản phẩm; Lịch khởi hành ghi nhiều ngày = nhiều đoàn. "
            "Tần suất = TB số đoàn/tháng/sản phẩm (tổng đoàn ÷ số sản phẩm). "
            "Giá TB có trọng số theo đoàn; khi biên độ luxury/phổ thông lớn: cắt 10% hai đầu + median. "
            "Giá thị trường = Giá TB/ngày × Số ngày TB."
        ),
        "totals": {
            "tours": total_tours,
            "departure_monthly": round(total_departures, 1),
            "avg_departures_per_month": round(total_departures / total_tours, 1) if total_tours else 0,
            "markets": len(markets),
            "companies": len(companies),
        },
        "vietravel": vtr_agg,
        "market_avg": mkt_agg,
        "markets": markets[:40],
        "companies": companies[:30],
        "routes": routes[:50],
    }


def build_price_analysis(tours: list[Tour], group_by: str = "thi_truong") -> list[dict]:
    """Phân tích giá theo nhóm — dùng TB robust có trọng số đoàn."""
    tours = deduplicate_tours(tours)
    key_map = {
        "thi_truong": lambda m: m["thi_truong"],
        "cong_ty": lambda m: m["cong_ty"],
        "tuyen_tour": lambda m: f"{m['thi_truong']} · {m['tuyen_tour']}" if m["tuyen_tour"] else m["thi_truong"],
    }
    getter = key_map.get(group_by, key_map["thi_truong"])

    by_group: dict[str, list[dict]] = defaultdict(list)
    for t in tours:
        m = _tour_metrics(t)
        if not m:
            continue
        g = getter(m)
        if not g:
            continue
        by_group[g].append(m)

    rows = []
    for group, items in by_group.items():
        prices = [(i["gia"], i["freq"]) for i in items]
        pd_pairs = [(i["price_day"], i["freq"]) for i in items]
        freq_total = sum(i["freq"] for i in items)
        rows.append({
            "group": group,
            "count": len(items),
            "min_gia": round(min(i["gia"] for i in items), 0),
            "max_gia": round(max(i["gia"] for i in items), 0),
            "avg_gia": robust_weighted_avg(prices),
            "median_gia": weighted_median(prices),
            "avg_price_day": robust_weighted_avg(pd_pairs),
            "departure_monthly": round(freq_total, 1),
            "avg_departures_per_month": round(freq_total / len(items), 1),
        })
    return sorted(rows, key=lambda x: -x["departure_monthly"])
