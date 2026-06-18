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
import re
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
    from models import Tour, FestivalTourMapping
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

    from provinces import get_region_for_code

    offset = 0
    while offset < total:
        tours = q.offset(offset).limit(TOUR_BATCH_SIZE).all()
        if not tours:
            break
        batch_tour_ids: list[int] = []          # tour trong batch (để xoá link source='date' cũ)
        batch_links: list[dict] = []            # link source='date' mới
        for t in tours:
            scanned += 1
            batch_tour_ids.append(t.id)
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

            # 3. Gom MỌI lễ trong ngưỡng (nhiều lễ/tour → bảng nối); best = lễ primary (cache).
            best_slug: str | None = None
            best_distance: int | None = None
            best_eff: int | None = None
            for f in festivals:
                dist = _compute_min_distance(tour_dates, f.date_start, f.date_end)
                if dist is None or abs(dist) > distance_threshold:
                    continue
                effective_dist = abs(dist)
                if t.province_code and f.province_code and t.province_code == f.province_code:
                    effective_dist = max(0, effective_dist - 1)
                elif t.province_code and f.region:
                    tour_region = get_region_for_code(t.province_code)
                    if tour_region and tour_region == f.region:
                        effective_dist = max(0, effective_dist - 1)
                batch_links.append({
                    "festival_id": f.id, "tour_id": t.id, "festival_slug": f.slug,
                    "distance_days": dist, "source": "date",
                })
                if best_eff is None or effective_dist < best_eff:
                    best_eff = effective_dist
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

        # Sync bảng nối cho batch: xoá link source='date' cũ (KHÔNG đụng 'rule'/'manual')
        # rồi chèn lại. Re-tag theo ngày không xoá link do rule/manual gán.
        if batch_tour_ids:
            db.query(FestivalTourMapping).filter(
                FestivalTourMapping.tour_id.in_(batch_tour_ids),
                FestivalTourMapping.source == "date",
            ).delete(synchronize_session=False)
            if batch_links:
                db.bulk_insert_mappings(FestivalTourMapping, batch_links)

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


# Region → thị trường VN tour database
# Tour DB dùng thi_truong như "Việt Nam", "Hàn Quốc", "Nhật Bản", ...
_REGION_TO_TOUR_THI_TRUONG = {
    "bac": ["miền bắc", "việt nam"],
    "trung": ["miền trung", "việt nam"],
    "nam": ["miền nam", "việt nam"],
}

# Map intl country → tour thị trường keywords
_INTL_COUNTRY_TO_TOUR_MARKET = {
    "hàn quốc": ["hàn quốc", "han quoc", "korea"],
    "nhật bản": ["nhật bản", "nhat ban", "japan"],
    "trung quốc": ["trung quốc", "trung quoc", "china"],
    "thái lan": ["thái lan", "thai lan", "thailand"],
    "singapore": ["singapore"],
    "mỹ": ["mỹ", "my", "hoa kỳ", "usa", "america"],
    "pháp": ["pháp", "phap", "france"],
    "đức": ["đức", "duc", "germany"],
    "ý": ["ý", "y", "italy"],
    "úc": ["úc", "uc", "australia"],
    "ấn độ": ["ấn độ", "an do", "india"],
    "indonesia": ["indonesia"],
    "malaysia": ["malaysia"],
    "philippines": ["philippines"],
    "đài loan": ["đài loan", "dai loan", "taiwan"],
    "lào": ["lào", "lao", "laos"],
    "campuchia": ["campuchia", "cambodia"],
    "anh": ["anh", "uk", "england", "britain"],
}


# Country names trong tour.thi_truong = tour đi NƯỚC NGOÀI. Khi festival VN
# match keyword như "Hà Nội", tour Trung Quốc xuất phát từ Hà Nội cũng match
# diem_kh="Hà Nội" → false positive. Loại bỏ tour có thi_truong là country
# khi match VN festival.
_FOREIGN_MARKET_KEYWORDS = [
    "trung quốc", "trung quoc", "china",
    "hàn quốc", "han quoc", "korea",
    "nhật bản", "nhat ban", "japan",
    "thái lan", "thai lan", "thailand",
    "singapore",
    "malaysia",
    "indonesia",
    "philippines",
    "đài loan", "dai loan", "taiwan",
    "hong kong",
    "lào", "laos",
    "campuchia", "cambodia",
    "myanmar",
    "ấn độ", "an do", "india",
    "úc", "australia",
    "mỹ", "usa", "america", "hoa kỳ",
    "canada",
    "pháp", "phap", "france",
    "đức", "duc", "germany",
    "anh", "uk", "england",
    "ý", "italy",
    "tây ban nha", "spain",
    "nga", "russia",
    "thụy sĩ", "thuy si", "switzerland",
    "hà lan", "ha lan", "netherlands",
    "brazil",
    "bắc âu", "bac au", "tây âu", "tay au", "nam âu", "đông âu",
    "trung đông",
    "châu âu", "chau au", "europe",
    "châu phi", "chau phi", "africa",
    "châu mỹ",
]


def _location_match_filter(f, Tour):
    """Build SQL filter cho tour ở CÙNG ĐÍCH ĐẾN với 1 festival.

    QUAN TRỌNG: dùng destination (tuyen_tour, thi_truong), KHÔNG dùng diem_kh
    (= điểm khởi hành). Bug cũ: tour Trung Quốc khởi hành từ Hà Nội match
    diem_kh="Hà Nội" → match nhầm festival ở Hà Nội.

    Logic:
      - Festival VN: tour.tuyen_tour chứa province name VÀ tour.thi_truong
        KHÔNG phải nước ngoài (loại tour outbound từ VN).
      - Festival intl: tour.thi_truong chứa country name của festival.

    Trả None nếu không extract được keyword.
    """
    from sqlalchemy import or_, and_, not_, func

    keywords: list[str] = []

    # Extract location keywords từ festival.location_text
    location_clean = (f.location_text or "").strip()
    parts = [p.strip() for p in location_clean.split(",") if p.strip()]
    for p in parts:
        cleaned = re.sub(r"^(t\.|tp\.|p\.|x\.|h\.|q\.)\s*", "", p, flags=re.IGNORECASE).strip()
        if cleaned and len(cleaned) >= 3:
            keywords.append(cleaned.lower())

    is_intl = f.region == "intl"

    if is_intl:
        # Intl festival: expand keyword tập tên nước (vd "Hàn Quốc" → ["hàn quốc", "korea", "kr"])
        intl_keywords: list[str] = []
        for _vn_name, keys in _INTL_COUNTRY_TO_TOUR_MARKET.items():
            if any(k.lower() in location_clean.lower() for k in keys):
                intl_keywords.extend(keys)
        if not intl_keywords:
            intl_keywords = keywords  # fallback dùng raw
        if not intl_keywords:
            return None
        # Match tour.thi_truong (market category) với country
        conds = [func.lower(Tour.thi_truong).like(f"%{k.lower()}%") for k in intl_keywords[:5]]
        return or_(*conds)

    # VN festival branch
    if not keywords:
        return None
    # Match tuyen_tour chứa province
    dest_conds = [func.lower(Tour.tuyen_tour).like(f"%{kw}%") for kw in keywords[:5]]
    dest_match = or_(*dest_conds)
    # Loại tour có thi_truong = nước ngoài (tour outbound, không phải tour nội địa)
    foreign_excludes = [
        ~func.lower(Tour.thi_truong).like(f"%{fk}%")
        for fk in _FOREIGN_MARKET_KEYWORDS
    ]
    return and_(dest_match, *foreign_excludes)


def get_festival_tours_summary(db, slug: str) -> dict[str, Any]:
    """Stats nhanh cho 1 festival: số tour gắn + ở cùng location.

    "Cùng location" = tour có diem_kh / tuyen_tour / thi_truong chứa keyword
    location của festival (vd lễ Đắk Lắk → tour Đắk Lắk).
    """
    import re
    from models import Festival, Tour
    from sqlalchemy import func, and_

    f = db.query(Festival).filter(Festival.slug == slug).first()
    if not f:
        return {"error": "Festival không tồn tại"}

    from tour_filters import market_filter_clause

    loc_filter = _location_match_filter(f, Tour)
    # Filter: tour có festival_slug = slug HOẶC (location match AND date overlap)
    # Nhưng để consistency: chỉ giữ tour đã được tag (festival_slug = slug)
    # VÀ location match (nếu có filter).
    base_query = db.query(Tour).filter(
        Tour.festival_slug == slug,
        market_filter_clause(Tour),
    )
    if loc_filter is not None:
        base_query = base_query.filter(loc_filter)

    total = base_query.count()
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
    by_company_q = (
        db.query(Tour.cong_ty, func.count(Tour.id))
        .filter(Tour.festival_slug == slug)
        .filter(market_filter_clause(Tour))
    )
    if loc_filter is not None:
        by_company_q = by_company_q.filter(loc_filter)
    by_company = dict(by_company_q.group_by(Tour.cong_ty).all())

    # Avg price (chỉ tour có giá hợp lý, loại outlier + market "Không xác định")
    avg_price_q = (
        db.query(func.avg(Tour.gia))
        .filter(
            Tour.festival_slug == slug,
            Tour.gia.isnot(None),
            Tour.gia >= 500_000,
            Tour.gia <= 500_000_000,
            market_filter_clause(Tour),
        )
    )
    if loc_filter is not None:
        avg_price_q = avg_price_q.filter(loc_filter)
    avg_price = avg_price_q.scalar()

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
    """Coverage gap: festival nào competitor cover ở ĐÚNG location mà VTR miss.

    "Cover" = tour có festival_slug match VÀ tour location match festival location.
    Sort theo gap_score desc → festival VTR thiếu nhất ở đầu.

    Performance: refactored từ N+1 query (200 festivals × 1 query/festival = 200 queries,
    ~10s tổng) → 1 query lấy tất cả tour có festival_slug + group in-memory.
    Redis cache TTL 1h (key = "ota:festival.coverage_gap:<hash(limit)>").
    """
    from redis_cache import make_key, redis_get, redis_set

    # v2 — bump after Fix A/B/C (has_rule key + expanded matching) so stale
    # pre-fix cache entries (missing has_rule) are not served.
    cache_key = make_key("festival.coverage_gap", limit=limit, v=2)
    cached = redis_get(cache_key)
    if cached is not None:
        return cached
    result = _compute_coverage_gap(db, limit)
    try:
        redis_set(cache_key, result, ttl=3600)
    except Exception:  # noqa: BLE001
        pass
    return result


def _compute_coverage_gap(db, limit: int) -> list[dict[str, Any]]:
    """Coverage gap v2 — Issue #5 Phase A.

    Counts BOTH:
      - "tagged" tour: Tour.festival_slug = f.slug (đã chạy festival tagging).
      - "implied" tour: tour match qua FestivalTourMappingRule
            (Festival.location_text contains rule.location_keyword
             AND Tour.thi_truong = rule.market_keyword [nếu có]
             AND Tour.tuyen_tour ILIKE %rule.route_keyword% [nếu có]
             AND Tour.lich_kh date overlap festival range — kiểm in-memory).

    Performance:
      - 1 query festivals (≤ 200).
      - 1 query FestivalTourMappingRule (≤ ~100). Build lookup by lowered
        location_keyword.
      - 1 query tour có festival_slug (existing).
      - 1 query tour matching ANY rule (market_keyword / route_keyword filter
        gộp OR). Tránh N+1.
    """
    from collections import defaultdict

    from models import Festival, FestivalTourMappingRule, Tour
    from sqlalchemy import and_, or_, func
    from sqlalchemy.orm import load_only
    from tour_filters import market_filter_clause

    today = date.today()
    festivals = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .order_by(Festival.date_start.asc())
        .limit(200)
        .all()
    )
    if not festivals:
        return []

    # ── Block 1: tagged tours (Tour.festival_slug = slug) ───────────────────
    fest_slugs = {f.slug for f in festivals}
    tagged_tour_rows = (
        db.query(Tour)
        .options(load_only(
            Tour.id, Tour.cong_ty, Tour.festival_slug, Tour.lich_kh,
            Tour.province_code, Tour.thi_truong, Tour.tuyen_tour,
        ))
        .filter(Tour.festival_slug.in_(fest_slugs))
        .filter(market_filter_clause(Tour))
        .all()
    )
    tagged_by_slug: dict[str, list[Tour]] = defaultdict(list)
    for t in tagged_tour_rows:
        if t.festival_slug:
            tagged_by_slug[t.festival_slug].append(t)

    # ── Block 2: load mapping rules ────────────────────────────────────────
    rules = (
        db.query(FestivalTourMappingRule)
        .filter(FestivalTourMappingRule.active == True)  # noqa: E712
        .all()
    )

    # For each festival, pick matching rules. Fix B — match if ANY of:
    #   • rule.location_keyword (lower) ∈ festival.location_text (lower)   [origin]
    #   • rule.location_keyword (lower) ∈ festival.name_vi/name_en (lower) [city in name,
    #     vd "Seoul Food" name chứa "Seoul" → rule location_keyword="Seoul" match]
    #   • rule.market_keyword (lower) ∈ festival.location_text (lower)     [country/region,
    #     vd festival location_text="Hàn Quốc" + rule market_keyword="Hàn Quốc"]
    rules_per_festival: dict[str, list[Any]] = {}
    for f in festivals:
        loc_text = (f.location_text or "").lower()
        name_text = ((f.name_vi or "") + " " + (f.name_en or "")).lower()
        matched: list[Any] = []
        seen_rule_ids: set[int] = set()
        for r in rules:
            if r.id in seen_rule_ids:
                continue
            kw = (r.location_keyword or "").strip().lower()
            mk = (r.market_keyword or "").strip().lower()
            hit = False
            if kw and (kw in loc_text or kw in name_text):
                hit = True
            elif mk and mk in loc_text:
                hit = True
            if hit:
                matched.append(r)
                seen_rule_ids.add(r.id)
        rules_per_festival[f.slug] = matched

    # ── Block 3: prefetch implied tour candidates ──────────────────────────
    # Build single OR filter cho mọi rule có ít nhất 1 trong market/route.
    # Lưu ý: tour rỗng festival_slug HOẶC khác slug đang xét — sẽ filter cụ thể
    # khi map về festival. Để giảm load, chỉ kéo tour có lich_kh != "".
    implied_filters = []
    for r in rules:
        cond = []
        if r.market_keyword and r.market_keyword.strip():
            cond.append(Tour.thi_truong == r.market_keyword.strip())
        if r.route_keyword and r.route_keyword.strip():
            cond.append(func.lower(Tour.tuyen_tour).like(f"%{r.route_keyword.strip().lower()}%"))
        if cond:
            implied_filters.append(and_(*cond))

    implied_tour_rows: list[Tour] = []
    if implied_filters:
        implied_tour_rows = (
            db.query(Tour)
            .options(load_only(
                Tour.id, Tour.cong_ty, Tour.festival_slug, Tour.lich_kh,
                Tour.province_code, Tour.thi_truong, Tour.tuyen_tour,
            ))
            .filter(or_(*implied_filters))
            .filter(Tour.lich_kh != "")
            .filter(market_filter_clause(Tour))
            .all()
        )

    # Per-rule matcher (in-memory). Tránh re-iter scan toàn bộ table per festival.
    def _tour_matches_rule(t: Tour, r: Any) -> bool:
        mk = (r.market_keyword or "").strip()
        if mk and (t.thi_truong or "") != mk:
            return False
        rk = (r.route_keyword or "").strip()
        if rk and rk.lower() not in (t.tuyen_tour or "").lower():
            return False
        return True

    # ── Block 4: build output ──────────────────────────────────────────────
    out: list[dict[str, Any]] = []
    for f in festivals:
        loc_filter_fn = _location_match_filter_fn(f)

        # tagged
        tagged = tagged_by_slug.get(f.slug, [])
        if loc_filter_fn is not None:
            tagged_filt = [t for t in tagged if loc_filter_fn(t)]
        else:
            tagged_filt = tagged

        # implied — chỉ tính nếu có rule match festival này.
        matched_rules = rules_per_festival.get(f.slug, [])
        implied_set: dict[int, Tour] = {}
        if matched_rules and implied_tour_rows:
            f_start, f_end = f.date_start, f.date_end
            # parse lich_kh dates lazy/cache per tour id để tránh re-parse.
            parsed_cache: dict[int, list] = {}
            for t in implied_tour_rows:
                if t.id in implied_set:
                    continue
                # Bỏ qua nếu đã tagged đúng slug — coi như cả tagged + implied
                # → tránh đếm 2 lần.
                if t.festival_slug == f.slug:
                    continue
                # rule match?
                if not any(_tour_matches_rule(t, r) for r in matched_rules):
                    continue
                # date overlap with festival range
                if t.id not in parsed_cache:
                    parsed_cache[t.id] = _parse_tour_lich_kh(t.lich_kh or "")
                tour_dates = parsed_cache[t.id]
                if not tour_dates:
                    continue
                # Sử dụng default window (DEFAULT_DISTANCE_THRESHOLD_DAYS); với
                # rule có date_window_days riêng, sẽ override per-rule. Lấy
                # window lớn nhất trong matched_rules để inclusive.
                max_window = max(
                    (int(getattr(r, "date_window_days", 0) or 0) for r in matched_rules),
                    default=DEFAULT_DISTANCE_THRESHOLD_DAYS,
                )
                if max_window <= 0:
                    max_window = DEFAULT_DISTANCE_THRESHOLD_DAYS
                dist = _compute_min_distance(tour_dates, f_start, f_end)
                if dist is None or abs(dist) > max_window:
                    continue
                if loc_filter_fn is not None and not loc_filter_fn(t):
                    continue
                implied_set[t.id] = t

        # Bucket VTR vs competitor cho cả tagged + implied (riêng).
        def _bucket(rows: list[Tour]) -> tuple[int, int, dict[str, int]]:
            vtr = 0
            comp = 0
            comp_companies: dict[str, int] = defaultdict(int)
            for t in rows:
                co = (t.cong_ty or "")
                if "vietravel" in co.lower():
                    vtr += 1
                else:
                    comp += 1
                    if co:
                        comp_companies[co] += 1
            return vtr, comp, comp_companies

        vtr_tagged, comp_tagged, comp_companies_tagged = _bucket(tagged_filt)
        implied_rows = list(implied_set.values())
        vtr_implied, comp_implied, comp_companies_implied = _bucket(implied_rows)

        vtr_total = vtr_tagged + vtr_implied
        comp_total = comp_tagged + comp_implied
        if vtr_total == 0 and comp_total == 0:
            continue

        # merge top_competitors
        merged_competitors: dict[str, int] = defaultdict(int)
        for k, v in comp_companies_tagged.items():
            merged_competitors[k] += v
        for k, v in comp_companies_implied.items():
            merged_competitors[k] += v

        out.append({
            "slug": f.slug,
            "name": f.name_vi,
            "date_start": f.date_start.isoformat(),
            "date_end": f.date_end.isoformat(),
            "region": f.region,
            "location": f.location_text or "",
            "location_text": f.location_text or "",
            "vtr_tours": vtr_total,
            "competitor_tours": comp_total,
            "vtr_tours_tagged": vtr_tagged,
            "vtr_tours_implied": vtr_implied,
            "competitor_tours_tagged": comp_tagged,
            "competitor_tours_implied": comp_implied,
            "top_competitors": dict(sorted(merged_competitors.items(), key=lambda kv: -kv[1])[:5]),
            "gap_score": comp_total - vtr_total * 1.5,
            "mapping_rule_ids": [str(r.id) for r in matched_rules],
            # Fix A/C — serialize BOTH keys: has_mapping_rule (back-compat) +
            # has_rule (what frontend FestivalsPage.tsx actually reads). Mismatch
            # of these keys was the root cause of "—" + has_rule===undefined.
            "has_mapping_rule": bool(matched_rules),
            "has_rule": bool(matched_rules),
        })
    out.sort(key=lambda x: -x["gap_score"])
    return out[:limit]


def get_coverage_gap_mapping_summary(db) -> dict[str, int]:
    """Issue #5 Phase A — Stats về festival nào có/không có mapping rule."""
    from models import Festival, FestivalTourMappingRule

    today = date.today()
    festivals = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .all()
    )
    rules = (
        db.query(FestivalTourMappingRule)
        .filter(FestivalTourMappingRule.active == True)  # noqa: E712
        .all()
    )
    # Use the SAME expanded matching as _compute_coverage_gap (Fix B) so the
    # header count ("X/Y festival có mapping rule") agrees with per-row "Có rule".
    def _festival_has_rule(f) -> bool:
        loc = (f.location_text or "").lower()
        name = ((f.name_vi or "") + " " + (f.name_en or "")).lower()
        for r in rules:
            kw = (r.location_keyword or "").strip().lower()
            mk = (r.market_keyword or "").strip().lower()
            if kw and (kw in loc or kw in name):
                return True
            if mk and mk in loc:
                return True
        return False

    with_rule = 0
    without_rule = 0
    for f in festivals:
        if _festival_has_rule(f):
            with_rule += 1
        else:
            without_rule += 1
    return {
        "total_festivals": len(festivals),
        "festivals_with_rule": with_rule,
        "festivals_without_rule": without_rule,
    }


def suggest_festival_mapping_rules(db, limit: int = 20) -> list[dict[str, Any]]:
    """Issue #5 Phase A — Auto-suggest mapping cho top under-served festivals.

    Logic:
      1. Lấy festivals upcoming chưa có rule match (location_text không match
         bất kỳ location_keyword nào).
      2. Score by "under-served": comp_tagged + comp_implied (đo bằng tour
         match location keyword festival → có hiện hữu cần map nhưng chưa).
      3. Suggest top cluster (market, route) của tour ở cùng location.
    """
    from collections import defaultdict
    from models import Festival, FestivalTourMappingRule, Tour
    from sqlalchemy import func
    from tour_filters import market_filter_clause

    today = date.today()
    festivals = (
        db.query(Festival)
        .filter(Festival.date_end >= today)
        .order_by(Festival.date_start.asc())
        .all()
    )
    rules = (
        db.query(FestivalTourMappingRule)
        .filter(FestivalTourMappingRule.active == True)  # noqa: E712
        .all()
    )
    existing_kws = {(r.location_keyword or "").strip().lower() for r in rules if r.location_keyword}

    out: list[dict[str, Any]] = []
    for f in festivals:
        loc_text = (f.location_text or "").strip()
        if not loc_text:
            continue
        # skip nếu đã có rule match
        loc_low = loc_text.lower()
        if any(kw and kw in loc_low for kw in existing_kws):
            continue

        # Suggested keyword = phần đầu location_text trước dấu phẩy.
        first_part = loc_text.split(",")[0].strip()
        if not first_part or len(first_part) < 3:
            continue
        # Strip prefix t./tp./p./x./h./q.
        cleaned = re.sub(r"^(t\.|tp\.|p\.|x\.|h\.|q\.)\s*", "", first_part, flags=re.IGNORECASE).strip()
        suggested_loc = cleaned or first_part

        # Tour clusters by (market, route) — chỉ tour có tuyen_tour chứa suggested_loc
        cluster_q = (
            db.query(Tour.thi_truong, Tour.tuyen_tour, func.count(Tour.id))
            .filter(market_filter_clause(Tour))
            .filter(func.lower(Tour.tuyen_tour).like(f"%{suggested_loc.lower()}%"))
            .filter(Tour.thi_truong != "")
            .filter(Tour.tuyen_tour != "")
            .group_by(Tour.thi_truong, Tour.tuyen_tour)
            .order_by(func.count(Tour.id).desc())
            .limit(3)
            .all()
        )
        if not cluster_q:
            continue
        top_market, top_route, top_count = cluster_q[0]
        total_in_loc = sum(c for _, _, c in cluster_q)
        confidence = round(top_count / total_in_loc, 2) if total_in_loc else 0.0

        out.append({
            "festival_slug": f.slug,
            "festival_name": f.name_vi,
            "location_text": loc_text,
            "suggested_location_keyword": suggested_loc,
            "suggested_market": top_market or "",
            "suggested_route": top_route or "",
            "confidence": confidence,
            "tour_count": int(top_count),
            "reasoning": (
                f"Top cluster {top_count}/{total_in_loc} tour ở \"{suggested_loc}\" → "
                f"{top_market}/{top_route}."
            ),
        })
        if len(out) >= limit:
            break
    return out


def _location_match_filter_fn(festival):
    """Trả về function(tour) → bool — version in-memory của _location_match_filter (SQL).
    Logic: tour.province_code match festival.province_code hoặc fallback substring match
    location_text trong tuyen_tour/thi_truong."""
    fest_prov = (getattr(festival, "province_code", "") or "").strip().upper()
    fest_loc = (getattr(festival, "location_text", "") or "").strip().lower()
    if not fest_prov and not fest_loc:
        return None

    # Substring keywords từ location_text
    keywords = []
    if fest_loc:
        # Lấy phần đầu (province name) - vd "Hà Nội, Việt Nam" → "hà nội"
        first_part = fest_loc.split(",")[0].strip()
        if first_part:
            keywords.append(first_part)

    def matcher(tour) -> bool:
        if fest_prov:
            tour_prov = (tour.province_code or "").strip().upper()
            if tour_prov and tour_prov == fest_prov:
                return True
        if keywords:
            tuyen = (tour.tuyen_tour or "").lower()
            tt = (tour.thi_truong or "").lower()
            for kw in keywords:
                if kw in tuyen or kw in tt:
                    return True
        return False

    return matcher
