"""Festival Insights Engine (T3 Phase 3).

3 use case chính:
  UC#2 — Pricing Premium: so giá tour gắn lễ vs tour cùng tuyến KHÔNG gắn lễ
  UC#3 — Demand Forecast: tháng có nhiều lễ → tăng inventory tour vùng đó
  UC#5 — Marketing Calendar: timeline 12 tháng cho marketing team

Output: structured dict cho API JSON, frontend chart/table.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# Hợp lý range giá tour VN (VND): 500K - 500M.
# Trên 500M (vd 724 nghìn tỷ trong DB) chắc chắn là data corruption.
# Dưới 500K không phải tour trọn gói (chỉ vé hoặc DV combo lẻ).
TOUR_PRICE_MIN_VND = 500_000
TOUR_PRICE_MAX_VND = 500_000_000

# Premium % cap — premium > 500% gần như chắc chắn do outlier.
PREMIUM_PCT_CAP = 500.0


def get_pricing_premium(db, top_n: int = 20) -> dict[str, Any]:
    """UC#2 — So giá tour gắn lễ vs không gắn lễ cùng tuyến.

    Pipeline:
      1. Filter tour gia trong range hợp lý 500K-500M (loại outlier corruption).
      2. Group theo (thi_truong, tuyen_tour, has_festival).
      3. Tính median (không phải mean) → robust với outlier.
      4. Premium % = (median_le - median_thuong) / median_thuong * 100.
      5. Skip nếu |premium| > 500% (chắc chắn data error).
      6. Sort theo premium desc.
    """
    from sqlalchemy import func, and_
    from models import Tour

    # Filter tour có giá trong range hợp lý + có thi_truong/tuyen_tour
    valid_filter = and_(
        Tour.gia.isnot(None),
        Tour.gia >= TOUR_PRICE_MIN_VND,
        Tour.gia <= TOUR_PRICE_MAX_VND,
        Tour.thi_truong != "",
        Tour.tuyen_tour != "",
    )

    # Lấy raw rows để compute median (SQL func.percentile chưa universal cross-DB)
    raw = (
        db.query(
            Tour.thi_truong,
            Tour.tuyen_tour,
            (Tour.festival_slug.isnot(None)).label("has_festival"),
            Tour.gia,
        )
        .filter(valid_filter)
        .all()
    )

    # Group: {(TT, Tuyến): {True: [gia_list], False: [gia_list]}}
    groups: dict[tuple[str, str], dict[bool, list[float]]] = defaultdict(lambda: {True: [], False: []})
    for r in raw:
        groups[(r.thi_truong, r.tuyen_tour)][bool(r.has_festival)].append(float(r.gia))

    def _median(xs: list[float]) -> float:
        if not xs:
            return 0.0
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        mid = n // 2
        if n % 2 == 1:
            return xs_sorted[mid]
        return (xs_sorted[mid - 1] + xs_sorted[mid]) / 2

    premiums: list[dict[str, Any]] = []
    for (tt, tuyen), buckets in groups.items():
        list_le = buckets[True]
        list_thuong = buckets[False]
        n_le = len(list_le)
        n_thuong = len(list_thuong)
        if n_le < 2 or n_thuong < 3:
            continue
        med_le = _median(list_le)
        med_thuong = _median(list_thuong)
        if med_thuong < 1:
            continue
        premium_pct = (med_le - med_thuong) / med_thuong * 100
        # Cap outlier (premium > 500% hoặc < -90% chắc chắn data error)
        if abs(premium_pct) > PREMIUM_PCT_CAP:
            continue
        premiums.append({
            "thi_truong": tt,
            "tuyen_tour": tuyen,
            "n_with_festival": n_le,
            "n_without_festival": n_thuong,
            "avg_price_with_festival": round(med_le),
            "avg_price_without_festival": round(med_thuong),
            "premium_pct": round(premium_pct, 1),
            "premium_vnd": round(med_le - med_thuong),
        })
    premiums.sort(key=lambda x: -x["premium_pct"])

    # Summary
    if premiums:
        avg_premium = sum(p["premium_pct"] for p in premiums) / len(premiums)
    else:
        avg_premium = 0
    total_le = sum(p["n_with_festival"] for p in premiums)
    total_thuong = sum(p["n_without_festival"] for p in premiums)
    return {
        "summary": {
            "routes_analyzed": len(premiums),
            "avg_premium_pct": round(avg_premium, 1),
            "tours_with_festival": total_le,
            "tours_without_festival": total_thuong,
        },
        "top_premium_routes": premiums[:top_n],
        "top_discount_routes": premiums[-top_n:][::-1] if len(premiums) > top_n else [],
    }


def get_demand_forecast(db, months_ahead: int = 6) -> dict[str, Any]:
    """UC#3 — Forecast tháng peak lễ → suggest tăng inventory.

    Output: cho mỗi tháng tới (months_ahead tháng), liệt kê:
      - Số lễ trong tháng
      - Top region (lễ tập trung vùng nào)
      - Inventory recommendation (low/medium/high)
      - Số tour hiện có gắn vào lễ đó
    """
    from models import Festival, Tour
    from sqlalchemy import func, and_

    today = date.today()
    out: list[dict[str, Any]] = []
    for offset in range(months_ahead):
        y = today.year + ((today.month - 1 + offset) // 12)
        m = ((today.month - 1 + offset) % 12) + 1
        month_start = date(y, m, 1)
        if m == 12:
            month_end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(y, m + 1, 1) - timedelta(days=1)
        # Festivals trong tháng
        festivals = (
            db.query(Festival)
            .filter(and_(
                Festival.date_start <= month_end,
                Festival.date_end >= month_start,
            ))
            .all()
        )
        festival_count = len(festivals)
        by_region: dict[str, int] = defaultdict(int)
        for f in festivals:
            by_region[f.region or "unknown"] += 1
        top_region = max(by_region.items(), key=lambda kv: kv[1])[0] if by_region else ""

        # Tour gắn vào festival trong tháng
        festival_slugs = [f.slug for f in festivals]
        tour_count = 0
        vtr_count = 0
        if festival_slugs:
            tour_count = db.query(Tour).filter(Tour.festival_slug.in_(festival_slugs)).count()
            vtr_count = (
                db.query(Tour)
                .filter(Tour.festival_slug.in_(festival_slugs))
                .filter(Tour.cong_ty.ilike("%vietravel%"))
                .count()
            )

        # Recommendation heuristic
        if festival_count >= 5:
            inventory_rec = "high"
            inventory_label = "Tăng inventory cao"
        elif festival_count >= 2:
            inventory_rec = "medium"
            inventory_label = "Tăng inventory vừa"
        else:
            inventory_rec = "low"
            inventory_label = "Inventory bình thường"

        out.append({
            "year": y,
            "month": m,
            "month_label": f"{m:02d}/{y}",
            "festival_count": festival_count,
            "top_region": top_region,
            "by_region": dict(by_region),
            "tour_count": tour_count,
            "vtr_tour_count": vtr_count,
            "competitor_tour_count": tour_count - vtr_count,
            "inventory_recommendation": inventory_rec,
            "inventory_label": inventory_label,
            "top_festivals": [
                {"slug": f.slug, "name": f.name_vi, "date_start": f.date_start.isoformat()}
                for f in sorted(festivals, key=lambda x: x.date_start)[:5]
            ],
        })
    return {"forecast": out}


def get_marketing_calendar(db, months_ahead: int = 12) -> list[dict[str, Any]]:
    """UC#5 — Marketing calendar: lễ hội cho 12 tháng + suggested tour push.

    Per festival, suggest top 3 tour Vietravel gắn lễ làm campaign push.
    """
    from sqlalchemy import and_
    from models import Festival, Tour

    today = date.today()
    until = today.replace(day=1)
    for _ in range(months_ahead):
        if until.month == 12:
            until = date(until.year + 1, 1, 1)
        else:
            until = date(until.year, until.month + 1, 1)

    festivals = (
        db.query(Festival)
        .filter(and_(
            Festival.date_end >= today,
            Festival.date_start <= until,
        ))
        .order_by(Festival.date_start.asc())
        .all()
    )

    out: list[dict[str, Any]] = []
    for f in festivals:
        # Top 3 tour VTR gắn lễ này (theo giá thấp nhất → bestseller candidate)
        vtr_tours = (
            db.query(Tour)
            .filter(Tour.festival_slug == f.slug)
            .filter(Tour.cong_ty.ilike("%vietravel%"))
            .filter(Tour.gia.isnot(None))
            .order_by(Tour.gia.asc())
            .limit(3)
            .all()
        )
        out.append({
            "slug": f.slug,
            "name": f.name_vi,
            "date_start": f.date_start.isoformat(),
            "date_end": f.date_end.isoformat(),
            "region": f.region,
            "category": f.category,
            "is_lunar": f.is_lunar,
            "suggested_tours": [
                {
                    "id": str(t.id),
                    "ten_tour": t.ten_tour,
                    "gia": t.gia,
                    "so_ngay": t.so_ngay,
                    "link_url": t.link_url,
                }
                for t in vtr_tours
            ],
            # Campaign hint
            "campaign_hint": _campaign_hint(f),
        })
    return out


def _campaign_hint(f) -> str:
    """Gợi ý loại campaign theo category + region."""
    cat = (f.category or "").lower()
    reg = (f.region or "").lower()
    if cat == "religious":
        return "Đề xuất tour tâm linh + chùa chiền + lễ hội Phật giáo"
    if cat == "cultural" and f.is_lunar:
        return "Tour gia đình + truyền thống — push 60 ngày trước"
    if cat == "music":
        return "Tour ngắn ngày + giới trẻ + booking online"
    if cat == "food":
        return "Tour ẩm thực địa phương + food tour 2-3 ngày"
    if cat == "sport":
        return "Tour kết hợp event thể thao + adventure"
    return "Tour văn hóa địa phương kết hợp festival"


def get_region_heatmap(db) -> dict[str, Any]:
    """UC#6 — Heatmap mật độ lễ × mật độ tour theo vùng.

    Output: cho mỗi region, đếm lễ + tour gắn lễ. Frontend render bar/map.
    """
    from sqlalchemy import func
    from models import Festival, Tour

    today = date.today()
    end = date(today.year + 1, 12, 31)

    # Festivals per region
    fest_rows = (
        db.query(Festival.region, func.count(Festival.id))
        .filter(Festival.date_end >= today, Festival.date_start <= end)
        .group_by(Festival.region)
        .all()
    )
    fest_by_region = {r or "unknown": int(c) for r, c in fest_rows}

    # Tours per region (province → region join)
    from provinces import get_region_for_code
    tour_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.province_code != "")
        .group_by(Tour.province_code)
        .all()
    )
    tour_by_region: dict[str, int] = defaultdict(int)
    for pc, cnt in tour_rows:
        r = get_region_for_code(pc)
        tour_by_region[r or "unknown"] += int(cnt)

    # Tours gắn lễ per region
    tour_fest_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.festival_slug.isnot(None))
        .filter(Tour.province_code != "")
        .group_by(Tour.province_code)
        .all()
    )
    tour_fest_by_region: dict[str, int] = defaultdict(int)
    for pc, cnt in tour_fest_rows:
        r = get_region_for_code(pc)
        tour_fest_by_region[r or "unknown"] += int(cnt)

    regions = ["bac", "trung", "nam"]
    out = []
    for r in regions:
        fest_n = fest_by_region.get(r, 0)
        tour_n = tour_by_region.get(r, 0)
        tour_fest_n = tour_fest_by_region.get(r, 0)
        ratio = (tour_fest_n / fest_n) if fest_n > 0 else 0
        out.append({
            "region": r,
            "region_label": {"bac": "Bắc", "trung": "Trung", "nam": "Nam"}[r],
            "festival_count": fest_n,
            "tour_count": tour_n,
            "tour_with_festival": tour_fest_n,
            "festival_coverage_ratio": round(ratio, 2),
            # Under-served = nhiều lễ nhưng ít tour gắn
            "is_under_served": fest_n >= 3 and ratio < 1.0,
        })
    return {"regions": out, "total_festivals": sum(fest_by_region.values())}
