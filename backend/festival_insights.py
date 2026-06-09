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


from redis_cache import cached_json


@cached_json("festival.pricing_premium", ttl=3600)
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
    from tour_filters import market_filter_clause

    # Filter tour có giá trong range hợp lý + có thi_truong/tuyen_tour
    # + loại trừ market "Không xác định" (rule toàn hệ thống)
    valid_filter = and_(
        Tour.gia.isnot(None),
        Tour.gia >= TOUR_PRICE_MIN_VND,
        Tour.gia <= TOUR_PRICE_MAX_VND,
        Tour.thi_truong != "",
        Tour.tuyen_tour != "",
        market_filter_clause(Tour),
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


@cached_json("festival.dashboard", ttl=3600)
def get_dashboard_summary(db) -> dict[str, Any]:
    """Smart dashboard summary cho landing tab Festival module.

    Trả các "smart alerts" + action hints — admin/analyst nhìn thấy ngay
    insight quan trọng nhất mà không cần click qua từng tab:

      1. Critical festivals 30d: lễ lớn trong 30 ngày tới mà VTR=0
      2. Under-served provinces: tỉnh có ≥2 lễ nhưng VTR=0
      3. Top coverage gap: lễ competitor cover mạnh nhất mà VTR bỏ lỡ
      4. Data quality: % lễ đã tag location_text, % tour đã có province_code
      5. Quick stats: total lễ upcoming, total tour gắn lễ, % cover VTR
    """
    from sqlalchemy import and_, func
    from models import Festival, Tour
    from tour_filters import market_filter_clause

    today = date.today()
    in_30d = today + timedelta(days=30)
    in_90d = today + timedelta(days=90)

    # ── 1. Critical festivals 30d (lễ sắp tới VTR=0) ───────────────────────
    upcoming_30 = (
        db.query(Festival)
        .filter(and_(
            Festival.date_start >= today,
            Festival.date_start <= in_30d,
        ))
        .order_by(Festival.date_start.asc())
        .limit(50)
        .all()
    )
    # Tour VTR cover các lễ này
    upcoming_slugs = [f.slug for f in upcoming_30]
    vtr_by_slug: dict[str, int] = defaultdict(int)
    if upcoming_slugs:
        rows = (
            db.query(Tour.festival_slug, func.count(Tour.id))
            .filter(Tour.festival_slug.in_(upcoming_slugs))
            .filter(Tour.cong_ty.ilike("%vietravel%"))
            .filter(market_filter_clause(Tour))
            .group_by(Tour.festival_slug)
            .all()
        )
        for s, c in rows:
            vtr_by_slug[s] = int(c)
    critical_30d = []
    for f in upcoming_30:
        if vtr_by_slug.get(f.slug, 0) == 0:
            critical_30d.append({
                "slug": f.slug,
                "name": f.name_vi,
                "date_start": f.date_start.isoformat(),
                "days_until": (f.date_start - today).days,
                "region": f.region,
                "location_text": f.location_text or "",
                "category": f.category,
            })

    # ── 2. Under-served provinces (≥2 lễ, VTR=0) ───────────────────────────
    fest_prov_rows = (
        db.query(Festival.province_code, func.count(Festival.id))
        .filter(Festival.date_end >= today, Festival.date_start <= in_90d)
        .filter(Festival.province_code != "")
        .group_by(Festival.province_code)
        .all()
    )
    vtr_prov_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.province_code != "")
        .filter(Tour.cong_ty.ilike("%vietravel%"))
        .group_by(Tour.province_code)
        .all()
    )
    vtr_by_prov = {pc: int(c) for pc, c in vtr_prov_rows}
    from provinces import get_name_for_code, get_region_for_code

    under_served = []
    for pc, fest_n in fest_prov_rows:
        if not pc:
            continue
        fest_n = int(fest_n)
        vtr_n = vtr_by_prov.get(pc, 0)
        if fest_n >= 2 and vtr_n == 0:
            under_served.append({
                "province_code": pc,
                "province_name": get_name_for_code(pc) or pc,
                "region": get_region_for_code(pc) or "",
                "festival_count": fest_n,
                "vtr_tour_count": vtr_n,
            })
    under_served.sort(key=lambda x: -x["festival_count"])

    # ── 3. Top coverage gap (lễ competitor cover mạnh, VTR thiếu) ──────────
    # Reuse get_coverage_gap top 5
    try:
        from festival_tagging import get_coverage_gap

        gap_top = get_coverage_gap(db, limit=5)
        top_gaps = [
            {
                "slug": g["slug"],
                "name": g["name"],
                "vtr_tours": g["vtr_tours"],
                "competitor_tours": g["competitor_tours"],
                "gap_score": g["gap_score"],
                "date_start": g["date_start"],
            }
            for g in gap_top
            if g["gap_score"] > 0
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("get_coverage_gap in dashboard failed: %s", e)
        top_gaps = []

    # ── 4. Data quality ────────────────────────────────────────────────────
    total_fest_upcoming = db.query(Festival).filter(Festival.date_end >= today).count()
    fest_with_loc = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .filter(Festival.location_text != "")
        .count()
    )
    fest_with_prov = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .filter(Festival.province_code != "")
        .count()
    )
    total_tours = db.query(Tour).count()
    tours_tagged = db.query(Tour).filter(Tour.festival_slug.isnot(None)).count()
    tours_with_prov = db.query(Tour).filter(Tour.province_code != "").count()

    # ── 5. Quick stats ─────────────────────────────────────────────────────
    upcoming_total_30 = len(upcoming_30)
    upcoming_total_90 = (
        db.query(Festival)
        .filter(and_(
            Festival.date_start <= in_90d,
            Festival.date_end >= today,
        ))
        .count()
    )
    vtr_tours_tagged = (
        db.query(Tour)
        .filter(Tour.festival_slug.isnot(None))
        .filter(Tour.cong_ty.ilike("%vietravel%"))
        .filter(market_filter_clause(Tour))
        .count()
    )

    return {
        "alerts": {
            "critical_30d_count": len(critical_30d),
            "critical_30d": critical_30d[:10],  # top 10
            "under_served_count": len(under_served),
            "under_served": under_served[:10],
            "top_gaps_count": len(top_gaps),
            "top_gaps": top_gaps,
        },
        "quick_stats": {
            "upcoming_30d": upcoming_total_30,
            "upcoming_90d": upcoming_total_90,
            "tours_tagged_festival": tours_tagged,
            "vtr_tours_tagged_festival": vtr_tours_tagged,
            "vtr_cover_ratio": round(vtr_tours_tagged / tours_tagged, 2) if tours_tagged > 0 else 0,
        },
        "data_quality": {
            "festivals_total": total_fest_upcoming,
            "festivals_with_location_pct": round(100 * fest_with_loc / total_fest_upcoming, 0) if total_fest_upcoming > 0 else 0,
            "festivals_with_province_pct": round(100 * fest_with_prov / total_fest_upcoming, 0) if total_fest_upcoming > 0 else 0,
            "tours_total": total_tours,
            "tours_with_province_pct": round(100 * tours_with_prov / total_tours, 0) if total_tours > 0 else 0,
            "tours_tagged_festival_pct": round(100 * tours_tagged / total_tours, 0) if total_tours > 0 else 0,
        },
    }


@cached_json("festival.demand_forecast", ttl=3600)
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
            from tour_filters import market_filter_clause
            tour_count = (
                db.query(Tour)
                .filter(Tour.festival_slug.in_(festival_slugs))
                .filter(market_filter_clause(Tour))
                .count()
            )
            vtr_count = (
                db.query(Tour)
                .filter(Tour.festival_slug.in_(festival_slugs))
                .filter(Tour.cong_ty.ilike("%vietravel%"))
                .filter(market_filter_clause(Tour))
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


@cached_json("festival.marketing", ttl=3600)
def get_marketing_calendar(db, months_ahead: int = 12) -> list[dict[str, Any]]:
    """UC#5 — Marketing calendar: lễ hội cho 12 tháng + suggested tour push.

    Per festival, suggest top 3 tour Vietravel gắn lễ làm campaign push.

    Performance: trước đây loop N festivals × 1 query/festival → N+1 queries.
    Với 200-500 festival trong 12 tháng + Render-CRDB latency ~50ms/query → 10-25s
    → Marketing tab trả 500 Internal Server Error do timeout.
    Giờ: 1 query lấy hết tour VTR có festival_slug → group in-memory → 1+1 queries.
    """
    from sqlalchemy import and_
    from sqlalchemy.orm import load_only
    from models import Festival, Tour
    from tour_filters import market_filter_clause

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

    # 1 query duy nhất: tất cả tour VTR có festival_slug trong range — load_only
    # giảm RAM/bytes wire. Sắp xếp theo gia asc để khi group sẽ giữ thứ tự "cheapest first".
    all_vtr_fest_tours = (
        db.query(Tour)
        .options(load_only(
            Tour.id, Tour.festival_slug, Tour.ten_tour, Tour.gia,
            Tour.so_ngay, Tour.link_url,
        ))
        .filter(Tour.festival_slug.isnot(None))
        .filter(Tour.cong_ty.ilike("%vietravel%"))
        .filter(Tour.gia.isnot(None))
        .filter(market_filter_clause(Tour))
        .order_by(Tour.gia.asc())
        .all()
    )

    # Group in-memory: {festival_slug: [top 3 cheapest tours]}
    tours_by_slug: dict[str, list[Tour]] = defaultdict(list)
    for t in all_vtr_fest_tours:
        slug = t.festival_slug
        if not slug or len(tours_by_slug[slug]) >= 3:
            continue
        tours_by_slug[slug].append(t)

    out: list[dict[str, Any]] = []
    for f in festivals:
        vtr_tours = tours_by_slug.get(f.slug, [])
        out.append({
            "slug": f.slug,
            "name": f.name_vi,
            "date_start": f.date_start.isoformat(),
            "date_end": f.date_end.isoformat(),
            "region": f.region,
            "location_text": f.location_text or "",
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


@cached_json("festival.heatmap", ttl=3600)
def get_region_heatmap(db) -> dict[str, Any]:
    """UC#6 — Heatmap mật độ lễ × mật độ tour.

    Output 2 chiều:
      - regions: 3 vùng Bắc/Trung/Nam (rollup)
      - provinces: per-province detail (top 20 by festival count) — bubble/heatmap

    Frontend render: bubble chart by province + region rollup bar.
    """
    from sqlalchemy import func
    from models import Festival, Tour

    today = date.today()
    end = date(today.year + 1, 12, 31)

    # ── Festivals: per province + per region ────────────────────────────────
    fest_prov_rows = (
        db.query(Festival.province_code, Festival.region, func.count(Festival.id))
        .filter(Festival.date_end >= today, Festival.date_start <= end)
        .group_by(Festival.province_code, Festival.region)
        .all()
    )
    fest_by_province: dict[str, int] = defaultdict(int)
    fest_by_region: dict[str, int] = defaultdict(int)
    for pc, region, c in fest_prov_rows:
        fest_by_province[pc or ""] += int(c)
        fest_by_region[region or "unknown"] += int(c)

    # ── Tours: per province (total + festival-tagged) ──────────────────────
    tour_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.province_code != "")
        .group_by(Tour.province_code)
        .all()
    )
    tour_by_province = {pc: int(c) for pc, c in tour_rows}

    tour_fest_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.festival_slug.isnot(None))
        .filter(Tour.province_code != "")
        .group_by(Tour.province_code)
        .all()
    )
    tour_fest_by_province = {pc: int(c) for pc, c in tour_fest_rows}

    # ── VTR tours per province (cho insight under-served) ──────────────────
    vtr_tour_rows = (
        db.query(Tour.province_code, func.count(Tour.id))
        .filter(Tour.province_code != "")
        .filter(Tour.cong_ty.ilike("%vietravel%"))
        .group_by(Tour.province_code)
        .all()
    )
    vtr_by_province = {pc: int(c) for pc, c in vtr_tour_rows}

    # ── Aggregate region rollup ─────────────────────────────────────────────
    from provinces import get_region_for_code, get_name_for_code

    tour_by_region: dict[str, int] = defaultdict(int)
    tour_fest_by_region: dict[str, int] = defaultdict(int)
    vtr_by_region: dict[str, int] = defaultdict(int)
    for pc, cnt in tour_by_province.items():
        r = get_region_for_code(pc) or "unknown"
        tour_by_region[r] += cnt
    for pc, cnt in tour_fest_by_province.items():
        r = get_region_for_code(pc) or "unknown"
        tour_fest_by_region[r] += cnt
    for pc, cnt in vtr_by_province.items():
        r = get_region_for_code(pc) or "unknown"
        vtr_by_region[r] += cnt

    regions = ["bac", "trung", "nam"]
    region_out = []
    for r in regions:
        fest_n = fest_by_region.get(r, 0)
        tour_n = tour_by_region.get(r, 0)
        tour_fest_n = tour_fest_by_region.get(r, 0)
        vtr_n = vtr_by_region.get(r, 0)
        ratio = (tour_fest_n / fest_n) if fest_n > 0 else 0
        region_out.append({
            "region": r,
            "region_label": {"bac": "Bắc", "trung": "Trung", "nam": "Nam"}[r],
            "festival_count": fest_n,
            "tour_count": tour_n,
            "tour_with_festival": tour_fest_n,
            "vtr_tour_count": vtr_n,
            "festival_coverage_ratio": round(ratio, 2),
            "is_under_served": fest_n >= 3 and ratio < 1.0,
        })

    # ── Per-province detail (chỉ trả province có festival HOẶC tour > 5) ────
    all_pcs = set(fest_by_province.keys()) | set(tour_by_province.keys())
    province_out: list[dict[str, Any]] = []
    for pc in all_pcs:
        if not pc:
            continue
        fest_n = fest_by_province.get(pc, 0)
        tour_n = tour_by_province.get(pc, 0)
        tour_fest_n = tour_fest_by_province.get(pc, 0)
        vtr_n = vtr_by_province.get(pc, 0)
        # Threshold: ít nhất 1 lễ HOẶC > 5 tour để khỏi spam province ít data
        if fest_n == 0 and tour_n < 5:
            continue
        ratio = (tour_fest_n / fest_n) if fest_n > 0 else 0
        province_out.append({
            "province_code": pc,
            "province_name": get_name_for_code(pc) or pc,
            "region": get_region_for_code(pc) or "",
            "festival_count": fest_n,
            "tour_count": tour_n,
            "tour_with_festival": tour_fest_n,
            "vtr_tour_count": vtr_n,
            "festival_coverage_ratio": round(ratio, 2),
            "is_under_served": fest_n >= 2 and (vtr_n == 0 or ratio < 0.5),
        })
    # Sort: under-served + festival_count desc
    province_out.sort(key=lambda x: (-int(x["is_under_served"]), -x["festival_count"], -x["tour_count"]))

    return {
        "regions": region_out,
        "provinces": province_out,
        "total_festivals": sum(fest_by_region.values()),
        "total_provinces_with_data": len(province_out),
    }
