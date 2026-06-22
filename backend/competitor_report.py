"""So sánh đối thủ 1:1 cho Báo cáo BGĐ (theo mẫu BP).

Cấu trúc: ĐẦU KHỞI HÀNH (đầu lớn trước) → THỊ TRƯỜNG → đi sâu TỪNG TUYẾN.
3 nhóm so sánh mỗi thị trường:
  • VTR (Vietravel)
  • ĐỐI THỦ: mỗi TUYẾN lấy công ty MẠNH NHẤT tuyến đó → 1 thị trường gồm nhiều cty.
  • CÔNG TY NGANG TẦM: Saigontourist (benchmark cố định).
Mỗi nhóm: số tuyến/sản phẩm/đoàn, giá từ + giá TB, tần suất THEO THÁNG (đoàn/tháng),
link. Số liệu auto-tính từ dữ liệu cào; admin điền 'Nhận định' (lưu AppKv, bền).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

_MIN_PRICE = 500_000
_MAX_PRICE = 500_000_000
_OVERRIDES_KEY = "competitor_report_overrides"
_PEER_KEYWORD = "saigontourist"  # "công ty ngang tầm" benchmark cố định


def _is_peer(cong_ty: str) -> bool:
    return _PEER_KEYWORD in (cong_ty or "").lower()


def _distinct_products(tours: list) -> int:
    return len({(t.ma_tour or t.ten_tour or "").strip().lower() for t in tours if (t.ma_tour or t.ten_tour)})


def _bucket_metrics(tours: list, dates_of: dict) -> dict[str, Any]:
    """Gộp 1 nhóm tour: sản phẩm (distinct), đoàn, giá từ/TB, link, đoàn theo tháng."""
    prods: set[str] = set()
    departures = 0
    price_min: float | None = None
    price_list: list[float] = []
    link = ""
    cheapest_name = ""
    month_count: Counter = Counter()
    for t in tours:
        key = (t.ma_tour or "").strip() or (t.ten_tour or "").strip().lower()
        if key:
            prods.add(key)
        ds = dates_of.get(t.id, [])
        departures += len(ds)
        for d in ds:
            month_count[f"{d.year:04d}-{d.month:02d}"] += 1
        if t.gia and _MIN_PRICE <= t.gia <= _MAX_PRICE:
            price_list.append(t.gia)
            if price_min is None or t.gia < price_min:
                price_min = t.gia
                link = t.link_url or ""
                cheapest_name = t.ten_tour or ""
        if not link and t.link_url:
            link = t.link_url
    monthly = [{"month": k, "count": v} for k, v in sorted(month_count.items())]
    return {
        "products": len(prods),
        "departures": departures,
        "price_from": float(price_min) if price_min else None,
        "price_avg": float(sum(price_list) / len(price_list)) if price_list else None,
        "link": link,
        "cheapest_name": cheapest_name,
        "monthly": monthly,
        "sell_from": monthly[0]["month"] if monthly else "",
        "sell_to": monthly[-1]["month"] if monthly else "",
    }


def build_competitor_report(db) -> dict[str, Any]:
    from compare_cache import get_compare_context
    from compare_engine import is_vietravel
    from festival_tagging import _parse_tour_lich_kh

    ctx = get_compare_context(db, [], "", "", allow_stale=False)
    tours = ctx.tours

    # Parse lich_kh 1 lần/tour (tránh parse lại nhiều lần khi gộp route/market/tháng).
    dates_of: dict[int, list] = {t.id: _parse_tour_lich_kh(t.lich_kh or "") for t in tours}

    by_dep: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for t in tours:
        dep = (t.diem_kh or "").strip() or "Không rõ"
        mkt = (t.thi_truong or "").strip() or "Không rõ"
        by_dep[dep][mkt].append(t)

    dep_counts = {d: sum(len(x) for x in m.values()) for d, m in by_dep.items()}
    dep_order = sorted(by_dep, key=lambda d: -dep_counts[d])

    def route_of(t) -> str:
        return (t.tuyen_tour or "").strip() or "Khác"

    departures_out: list[dict[str, Any]] = []
    for dep in dep_order:
        markets_out: list[dict[str, Any]] = []
        for mkt, mt in sorted(by_dep[dep].items(), key=lambda kv: -len(kv[1])):
            vtr = [t for t in mt if is_vietravel(t.cong_ty or "")]
            peer = [t for t in mt if _is_peer(t.cong_ty or "")]
            comp_all = [t for t in mt if not is_vietravel(t.cong_ty or "") and not _is_peer(t.cong_ty or "")]

            # ── Đi sâu TỪNG TUYẾN ───────────────────────────────────────────
            routes = sorted({route_of(t) for t in mt})
            routes_out: list[dict[str, Any]] = []
            comp_companies: set[str] = set()
            for rt in routes:
                rt_vtr = [t for t in vtr if route_of(t) == rt]
                rt_peer = [t for t in peer if route_of(t) == rt]
                rt_comp = [t for t in comp_all if route_of(t) == rt]
                # Đối thủ MẠNH NHẤT của tuyến này (nhiều sản phẩm nhất).
                by_co: dict[str, list] = defaultdict(list)
                for t in rt_comp:
                    by_co[(t.cong_ty or "(không rõ)")].append(t)
                strongest = max(by_co, key=lambda c: _distinct_products(by_co[c])) if by_co else ""
                if strongest:
                    comp_companies.add(strongest)
                rt_comp_best = by_co.get(strongest, [])
                if not (rt_vtr or rt_comp_best or rt_peer):
                    continue
                routes_out.append({
                    "tuyen": rt,
                    "vtr": _bucket_metrics(rt_vtr, dates_of) if rt_vtr else None,
                    "competitor": ({"company": strongest, **_bucket_metrics(rt_comp_best, dates_of)}) if rt_comp_best else None,
                    "peer": _bucket_metrics(rt_peer, dates_of) if rt_peer else None,
                })

            markets_out.append({
                "thi_truong": mkt,
                "competitor_companies": sorted(comp_companies),
                "has_peer": bool(peer),
                # Tổng hợp cấp thị trường cho 3 nhóm
                "vtr": _bucket_metrics(vtr, dates_of),
                "competitor": _bucket_metrics(comp_all, dates_of),
                "peer": _bucket_metrics(peer, dates_of),
                "vtr_routes": len([r for r in routes_out if r["vtr"]]),
                "competitor_routes": len([r for r in routes_out if r["competitor"]]),
                "peer_routes": len([r for r in routes_out if r["peer"]]),
                "routes": routes_out,
            })
        if markets_out:
            departures_out.append({
                "diem_kh": dep,
                "total_tours": dep_counts[dep],
                "markets": markets_out,
            })
    return {"departures": departures_out, "peer_name": "Saigontourist"}


def load_overrides(db) -> dict[str, Any]:
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _OVERRIDES_KEY).first()
    if not row or not row.value_json:
        return {}
    try:
        return json.loads(row.value_json)
    except json.JSONDecodeError:
        return {}


def save_overrides(db, data: dict[str, Any]) -> None:
    from models import AppKv
    payload = json.dumps(data, ensure_ascii=False)
    row = db.query(AppKv).filter(AppKv.key == _OVERRIDES_KEY).first()
    if row:
        row.value_json = payload
    else:
        db.add(AppKv(key=_OVERRIDES_KEY, value_json=payload))
    db.commit()
