"""So sánh đối thủ 1:1 cho Báo cáo BGĐ.

Cấu trúc (giống mẫu PDF của BP): theo ĐẦU KHỞI HÀNH (đầu lớn trước) → THỊ TRƯỜNG;
mỗi thị trường so VTR vs ĐỐI THỦ MẠNH NHẤT (auto = công ty nhiều sản phẩm nhất ở
đầu×thị trường đó) trên: số sản phẩm, giá từ (rẻ nhất), tần suất (đoàn), link, và
'Giá SS thị trường' (= giá đối thủ thấp nhất). Số liệu auto-tính từ dữ liệu cào;
admin chỉnh sửa/điền 'Nhận định' (lưu overrides qua AppKv, bền vĩnh viễn).
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

_MIN_PRICE = 500_000
_MAX_PRICE = 500_000_000
_OVERRIDES_KEY = "competitor_report_overrides"


def _dep_count(lich_kh: str) -> int:
    from festival_tagging import _parse_tour_lich_kh
    return len(_parse_tour_lich_kh(lich_kh or ""))


def _metrics(tours: list) -> dict[str, Any]:
    """Gộp 1 nhóm tour: số CHƯƠNG TRÌNH (distinct), tần suất (đoàn), giá từ + link."""
    prods: set[str] = set()
    departures = 0
    price_from: float | None = None
    link = ""
    cheapest_name = ""
    for t in tours:
        key = (t.ma_tour or "").strip() or (t.ten_tour or "").strip().lower()
        if key:
            prods.add(key)
        departures += _dep_count(t.lich_kh or "")
        if t.gia and _MIN_PRICE <= t.gia <= _MAX_PRICE:
            if price_from is None or t.gia < price_from:
                price_from = t.gia
                link = t.link_url or ""
                cheapest_name = t.ten_tour or ""
        if not link and t.link_url:
            link = t.link_url
    return {
        "products": len(prods),
        "departures": departures,
        "price_from": float(price_from) if price_from else None,
        "link": link,
        "cheapest_name": cheapest_name,
    }


def _distinct_products(tours: list) -> int:
    return len({(t.ma_tour or t.ten_tour or "").strip().lower() for t in tours if (t.ma_tour or t.ten_tour)})


def build_competitor_report(db) -> dict[str, Any]:
    """Auto-tính cấu trúc so sánh đối thủ từ compare context (toàn thị trường)."""
    from compare_cache import get_compare_context
    from compare_engine import is_vietravel

    ctx = get_compare_context(db, [], "", "", allow_stale=False)
    tours = ctx.tours

    by_dep: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for t in tours:
        dep = (t.diem_kh or "").strip() or "Không rõ"
        mkt = (t.thi_truong or "").strip() or "Không rõ"
        by_dep[dep][mkt].append(t)

    # Đầu khởi hành: sắp ĐẦU LỚN trước (tổng tour desc) → HCM, Hà Nội, Đà Nẵng…
    dep_counts = {d: sum(len(x) for x in m.values()) for d, m in by_dep.items()}
    dep_order = sorted(by_dep, key=lambda d: -dep_counts[d])

    departures_out: list[dict[str, Any]] = []
    for dep in dep_order:
        markets_out: list[dict[str, Any]] = []
        for mkt, tlist in sorted(by_dep[dep].items(), key=lambda kv: -len(kv[1])):
            vtr = [t for t in tlist if is_vietravel(t.cong_ty or "")]
            comp = [t for t in tlist if not is_vietravel(t.cong_ty or "")]
            if not vtr and not comp:
                continue
            # Đối thủ mạnh nhất = công ty (≠ VTR) nhiều CHƯƠNG TRÌNH nhất.
            comp_by_co: dict[str, list] = defaultdict(list)
            for t in comp:
                comp_by_co[(t.cong_ty or "(không rõ)")].append(t)
            strongest = max(comp_by_co, key=lambda c: _distinct_products(comp_by_co[c])) if comp_by_co else ""
            comp_tours = comp_by_co.get(strongest, [])
            # Giá SS thị trường = giá đối thủ thấp nhất ở đầu×thị trường.
            market_floor: float | None = None
            for t in comp:
                if t.gia and _MIN_PRICE <= t.gia <= _MAX_PRICE and (market_floor is None or t.gia < market_floor):
                    market_floor = t.gia
            markets_out.append({
                "thi_truong": mkt,
                "competitor": strongest,
                "competitor_company_count": len(comp_by_co),
                "vtr": _metrics(vtr),
                "competitor_metrics": _metrics(comp_tours),
                "market_price_from": float(market_floor) if market_floor else None,
            })
        if markets_out:
            departures_out.append({
                "diem_kh": dep,
                "total_tours": dep_counts[dep],
                "markets": markets_out,
            })
    return {"departures": departures_out}


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
