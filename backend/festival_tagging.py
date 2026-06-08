"""Festival-Tour Tagging Engine (T3 Phase 2 Use Case #1).

Auto-tag tour có lich_kh trong khoảng ±N ngày quanh festival.date_range.
Bonus: nếu tour.province_code khớp festival.province_code → match mạnh hơn.

Pipeline:
  1. Load active festivals (festivals.date_end >= today - WINDOW_DAYS).
  2. Loop tours (batched) có lich_kh không rỗng.
  3. Parse lich_kh (qua date_format_rules.match_text) → list[date].
  4. Mỗi date check khoảng cách (days) với festival.date_range.
  5. Pick festival có distance nhỏ nhất ≤ THRESHOLD → tour.festival_slug = slug.
  6. Cập nhật tour.province_code (resolve từ tour.diem_kh).

Cron: daily after sync chain. Idempotent — re-run không gây side effect.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Khoảng ngày coi là "gắn lễ": tour.lich_kh ±3 ngày quanh festival.date_range.
DEFAULT_DISTANCE_THRESHOLD_DAYS = 3
# Festival quá xa quá khứ không tính (tránh tag sai vào lễ năm trước).
ACTIVE_FESTIVAL_LOOKBACK_DAYS = 7
# Batch size để không OOM khi tour ~50k.
TOUR_BATCH_SIZE = 500


def _compute_min_distance(
    tour_dates: list[date],
    festival_start: date,
    festival_end: date,
) -> int | None:
    """Khoảng cách (ngày) tối thiểu từ list ngày tour tới date_range của lễ.

    Trả 0 nếu overlap. Trả số dương nếu tour trước lễ. Số âm nếu tour sau lễ.
    None nếu tour_dates rỗng.
    """
    if not tour_dates:
        return None
    best: int | None = None
    for d in tour_dates:
        if festival_start <= d <= festival_end:
            return 0  # overlap = best possible
        if d < festival_start:
            dist = (festival_start - d).days  # dương: tour trước lễ
        else:
            dist = -(d - festival_end).days   # âm: tour sau lễ
        if best is None or abs(dist) < abs(best):
            best = dist
    return best


def _parse_tour_lich_kh(text: str) -> list[date]:
    """Parse Tour.lich_kh → list[date] via DSL match_text."""
    if not text or not text.strip():
        return []
    try:
        from date_format_rules import match_text
        dates_dt, _ot, _rid = match_text(text)
        return [d.date() if isinstance(d, datetime) else d for d in dates_dt]
    except Exception as e:  # noqa: BLE001
        logger.debug("Parse lich_kh failed: %s", e)
        return []


def _load_active_festivals(db) -> list[Any]:
    """Lấy festivals còn active (date_end >= today - lookback)."""
    from models import Festival

    today = date.today()
    cutoff = today - timedelta(days=ACTIVE_FESTIVAL_LOOKBACK_DAYS)
    return (
        db.query(Festival)
        .filter(Festival.date_end >= cutoff)
        .order_by(Festival.date_start.asc())
        .all()
    )


def tag_tours_with_festivals(
    db,
    distance_threshold: int = DEFAULT_DISTANCE_THRESHOLD_DAYS,
    only_untagged: bool = False,
) -> dict[str, int]:
    """Top-level: scan mọi tour có lich_kh, gán festival_slug + province_code.

    Args:
        db: SQLAlchemy session
        distance_threshold: số ngày tối đa từ tour → festival để coi là "gắn"
        only_untagged: True = chỉ tag tour chưa có festival_slug. False = re-tag all.

    Returns:
        Stats {tours_scanned, tours_tagged, tours_cleared, tours_province_updated}
    """
    from models import Tour
    from provinces import resolve_province_code

    festivals = _load_active_festivals(db)
    if not festivals:
        logger.info("Festival tagging: chưa có lễ hội active, skip")
        return {"tours_scanned": 0, "tours_tagged": 0, "tours_cleared": 0, "tours_province_updated": 0}

    logger.info("Festival tagging: %d lễ hội active", len(festivals))

    # Build index theo region để filter pre-match nhanh hơn (cùng region ưu tiên)
    # Phase 2 đơn giản: scan toàn bộ festivals cho mỗi tour. ~50k tour × 100 festivals
    # = 5M ops → vẫn OK (~10-20s) với primitives.

    scanned = 0
    tagged = 0
    cleared = 0
    province_updated = 0

    q = db.query(Tour).filter(Tour.lich_kh != "")
    if only_untagged:
        q = q.filter(Tour.festival_slug.is_(None))
    total = q.count()
    logger.info("Festival tagging: scan %d tour", total)

    offset = 0
    while offset < total:
        tours = q.offset(offset).limit(TOUR_BATCH_SIZE).all()
        if not tours:
            break
        for t in tours:
            scanned += 1
            # 1. Update province_code from diem_kh (cache)
            current_province = (t.province_code or "")
            new_province = resolve_province_code(t.diem_kh or "")
            if new_province and new_province != current_province:
                t.province_code = new_province
                province_updated += 1

            # 2. Parse lich_kh
            tour_dates = _parse_tour_lich_kh(t.lich_kh)
            if not tour_dates:
                if t.festival_slug:
                    t.festival_slug = None
                    t.festival_distance_days = None
                    cleared += 1
                continue

            # 3. Find best festival match
            best_slug: str | None = None
            best_distance: int | None = None
            for f in festivals:
                dist = _compute_min_distance(tour_dates, f.date_start, f.date_end)
                if dist is None:
                    continue
                if abs(dist) > distance_threshold:
                    continue
                # Bonus: region match → ưu tiên (giảm |distance| 1 ngày khi cùng region)
                effective_dist = abs(dist)
                if t.province_code and f.province_code and t.province_code == f.province_code:
                    effective_dist = max(0, effective_dist - 1)
                elif t.province_code and f.region:
                    # Kiểm tra tour region match festival region
                    from provinces import get_region_for_code
                    tour_region = get_region_for_code(t.province_code)
                    if tour_region and tour_region == f.region:
                        effective_dist = max(0, effective_dist - 1)
                if best_distance is None or effective_dist < best_distance:
                    best_slug = f.slug
                    best_distance = dist

            if best_slug:
                if t.festival_slug != best_slug:
                    t.festival_slug = best_slug
                    t.festival_distance_days = best_distance
                    tagged += 1
                elif t.festival_distance_days != best_distance:
                    t.festival_distance_days = best_distance
            else:
                if t.festival_slug:
                    t.festival_slug = None
                    t.festival_distance_days = None
                    cleared += 1

        try:
            db.commit()
        except Exception as e:
            logger.exception("Commit festival tagging batch fail: %s", e)
            db.rollback()
        offset += TOUR_BATCH_SIZE

    stats = {
        "tours_scanned": scanned,
        "tours_tagged": tagged,
        "tours_cleared": cleared,
        "tours_province_updated": province_updated,
    }
    logger.info("Festival tagging done: %s", stats)
    return stats


def get_festival_tours_summary(db, slug: str) -> dict[str, Any]:
    """Stats nhanh cho 1 festival: số tour gắn, theo công ty, giá TB, etc."""
    from models import Festival, Tour
    from sqlalchemy import func

    f = db.query(Festival).filter(Festival.slug == slug).first()
    if not f:
        return {"error": "Festival không tồn tại"}

    q = db.query(Tour).filter(Tour.festival_slug == slug)
    total = q.count()
    if total == 0:
        return {
            "slug": slug,
            "name": f.name_vi,
            "total_tours": 0,
            "by_company": {},
            "avg_price": None,
            "vtr_tours": 0,
            "competitor_tours": 0,
        }

    # Group by company
    by_company = dict(
        db.query(Tour.cong_ty, func.count(Tour.id))
        .filter(Tour.festival_slug == slug)
        .group_by(Tour.cong_ty)
        .all()
    )
    # Avg price (chỉ tour có giá)
    avg_price = (
        db.query(func.avg(Tour.gia))
        .filter(Tour.festival_slug == slug, Tour.gia.isnot(None))
        .scalar()
    )
    # VTR vs competitor
    vtr = sum(c for co, c in by_company.items() if "vietravel" in (co or "").lower())
    return {
        "slug": slug,
        "name": f.name_vi,
        "total_tours": total,
        "by_company": {k or "(không rõ)": v for k, v in by_company.items()},
        "avg_price": float(avg_price) if avg_price else None,
        "vtr_tours": vtr,
        "competitor_tours": total - vtr,
    }


def get_coverage_gap(db, limit: int = 30) -> list[dict[str, Any]]:
    """Coverage gap: festival nào competitor có tour mà VTR không cover.

    Sort theo competitor_count desc → festival "hot" mà VTR đang miss.
    """
    from models import Festival, Tour
    from sqlalchemy import func

    today = date.today()
    festivals = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .order_by(Festival.date_start.asc())
        .limit(200)
        .all()
    )

    out: list[dict[str, Any]] = []
    for f in festivals:
        # Count tour gắn lễ này theo VTR vs khác
        rows = (
            db.query(Tour.cong_ty, func.count(Tour.id))
            .filter(Tour.festival_slug == f.slug)
            .group_by(Tour.cong_ty)
            .all()
        )
        vtr_count = 0
        comp_count = 0
        comp_companies: dict[str, int] = {}
        for co, cnt in rows:
            if "vietravel" in (co or "").lower():
                vtr_count += cnt
            else:
                comp_count += cnt
                if co:
                    comp_companies[co] = cnt
        if comp_count == 0 and vtr_count == 0:
            continue  # không lễ nào cover, skip
        out.append({
            "slug": f.slug,
            "name": f.name_vi,
            "date_start": f.date_start.isoformat(),
            "date_end": f.date_end.isoformat(),
            "region": f.region,
            "vtr_tours": vtr_count,
            "competitor_tours": comp_count,
            "top_competitors": dict(sorted(comp_companies.items(), key=lambda kv: -kv[1])[:5]),
            "gap_score": comp_count - vtr_count * 1.5,  # comp nhiều + VTR 0 = score cao
        })
    # Sort theo gap_score desc — VTR thiếu nhất ở đầu
    out.sort(key=lambda x: -x["gap_score"])
    return out[:limit]
