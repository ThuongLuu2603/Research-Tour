from __future__ import annotations

import time
import threading
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.auth import get_current_user
from compare_cache import get_compare_context, get_segment_by_key, load_tours
from data_sources import MIN_VALID_PRICE
from compare_engine import (
    METHODOLOGY,
    build_competitor_overview,
    deduplicate_tours,
    is_vietravel,
    normalize_departure,
    normalize_route,
    parse_segment_key,
)
from classification import collect_unmatched_values, resolve_company_name
from config import settings
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/compare", tags=["compare"])

# Cache /filter-options — dữ liệu này thay đổi ít, không cần rebuild mỗi request
_filter_options_cache: dict | None = None
_filter_options_ts: float = 0.0
_filter_options_lock = threading.Lock()
_FILTER_OPTIONS_TTL = 600.0  # 10 phút


class CompareSummary(BaseModel):
    company: str
    total_vietravel_tours: int
    vietravel_tab_tours: int
    total_market_tours: int
    segments_with_vietravel: int
    segments_comparable: int = 0  # tuyến TT có sản phẩm so sánh được (chênh giá tính được)
    cheaper_count: int
    expensive_count: int
    similar_count: int
    avg_gap_pct: float | None
    vtr_freq_monthly_total: float
    vtr_avg_departures_per_month: float | None = None
    market_freq_monthly_total: float
    freq_leading_segments: int
    freq_lagging_segments: int
    methodology: str


def _load_vtr_tours(db: Session, thi_truong: list[str], tuyen_tour: str = "", diem_kh: str = "") -> list[Tour]:
    # Cần ctx.tours (full) → không stale.
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False)
    return [t for t in ctx.tours if is_vietravel(t.cong_ty)]


def _build_filter_options_from_cache(db: Session) -> dict:
    """Lấy filter options từ compare cache (nếu warm) hoặc DB DISTINCT query (nếu cold)."""
    from tour_sources import is_vietravel_tab

    # Thử lấy từ compare cache trước (nếu đã warm)
    try:
        from compare_cache import _cache, _lock
        with _lock:
            base_hit = next(
                (v for k, v in _cache.items() if k[0] == () and k[1] == "" and k[2] == ""),
                None,
            )
        if base_hit:
            vtr_tours = [t for t in base_hit[1].tours if is_vietravel_tab(t)]
            markets = sorted({(t.thi_truong or "Khác").strip() for t in vtr_tours})
            routes_by_market: dict[str, list[str]] = defaultdict(list)
            all_routes: set[str] = set()
            deps: set[str] = set()
            for t in vtr_tours:
                m = (t.thi_truong or "Khác").strip()
                route = normalize_route(t.tuyen_tour) or m
                all_routes.add(route)
                if route not in routes_by_market[m]:
                    routes_by_market[m].append(route)
                deps.add(normalize_departure(t.diem_kh))
            for m in routes_by_market:
                routes_by_market[m] = sorted(routes_by_market[m])
            return {
                "thi_truong": markets,
                "tuyen_tour": sorted(all_routes),
                "diem_kh": sorted(deps),
                "routes_by_market": dict(routes_by_market),
            }
    except Exception:
        pass

    # Fallback: SQL DISTINCT — nhanh hơn load toàn bộ tour
    rows = (
        db.query(Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh)
        .filter(Tour.nguon == "Vietravel", Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)
        .distinct()
        .all()
    )
    markets: set[str] = set()
    routes_by_market2: dict[str, list[str]] = defaultdict(list)
    all_routes2: set[str] = set()
    deps2: set[str] = set()
    for r in rows:
        m = (r.thi_truong or "Khác").strip()
        markets.add(m)
        route = normalize_route(r.tuyen_tour) or m
        all_routes2.add(route)
        if route not in routes_by_market2[m]:
            routes_by_market2[m].append(route)
        deps2.add(normalize_departure(r.diem_kh))
    for m in routes_by_market2:
        routes_by_market2[m] = sorted(routes_by_market2[m])
    return {
        "thi_truong": sorted(markets),
        "tuyen_tour": sorted(all_routes2),
        "diem_kh": sorted(deps2),
        "routes_by_market": dict(routes_by_market2),
    }


@router.get("/filter-options")
def compare_filter_options(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    global _filter_options_cache, _filter_options_ts
    now = time.time()
    with _filter_options_lock:
        if _filter_options_cache is not None and now - _filter_options_ts < _FILTER_OPTIONS_TTL:
            return _filter_options_cache
    result = _build_filter_options_from_cache(db)
    with _filter_options_lock:
        _filter_options_cache = result
        _filter_options_ts = now
    return result


def invalidate_compare_filter_cache() -> None:
    global _filter_options_cache, _filter_options_ts
    with _filter_options_lock:
        _filter_options_cache = None
        _filter_options_ts = 0.0


@router.get("/classification-gaps")
def classification_gaps(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    no_filter = not (thi_truong or tuyen_tour or diem_kh)
    if no_filter:
        from persistent_cache import load_json
        _disk = load_json("compare_classgaps_default", max_age_hours=24)
        if _disk is not None:
            return _disk
    # Áp đủ filter (FE đã gửi) — trước đây bỏ tuyen_tour/diem_kh nên panel "Chưa map"
    # luôn tính trên toàn thị trường dù đang lọc theo tuyến/điểm KH.
    tours = _load_vtr_tours(db, thi_truong, tuyen_tour, diem_kh)
    result = collect_unmatched_values(tours, vtr_only=True)
    if no_filter:
        try:
            from persistent_cache import save_json
            save_json("compare_classgaps_default", result, ttl_hours=24)
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/summary", response_model=CompareSummary)
def compare_summary(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Redis cache TTL 5 phut. Key = filter params + DB fingerprint (auto invalidate
    # khi data thay doi). summarize_context iterates 7568 tours + 65 segments =
    # 6-8s compute. Cache hit < 50ms.
    from redis_cache import make_key, redis_get, redis_set
    from compare_cache import _db_fingerprint

    fp = _db_fingerprint(db)
    cache_key = make_key(
        "compare.summary",
        thi_truong=sorted(thi_truong), tuyen_tour=tuyen_tour, diem_kh=diem_kh,
        fp_count=fp[0], fp_updated=fp[1],
    )
    cached = redis_get(cache_key)
    if cached is not None:
        return CompareSummary(**cached)

    # Layer 2: Disk (24h) — ưu tiên dùng disk thay vì compute live 6s
    no_filter = not (thi_truong or tuyen_tour or diem_kh)
    if no_filter:
        from persistent_cache import load_json
        disk_data = load_json("compare_summary_default", max_age_hours=24)
        if disk_data:
            try:
                redis_set(cache_key, disk_data, ttl=300)
            except Exception:  # noqa: BLE001
                pass
            return CompareSummary(**disk_data)

    # Cần ctx.tours/segments (full) cho summarize_context → không stale.
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False)
    from compare_engine import summarize_context

    k = summarize_context(ctx.tours, ctx.segments)
    vtr_count = k["vtr_count"]
    vtr_freq = k["vtr_freq_monthly"]

    result = CompareSummary(
        company=settings.company_name,
        total_vietravel_tours=vtr_count,
        vietravel_tab_tours=vtr_count,
        total_market_tours=k["market_count"],
        segments_with_vietravel=k["segment_count"],
        segments_comparable=k.get("comparable_count", 0),
        cheaper_count=k["cheaper"],
        expensive_count=k["expensive"],
        similar_count=k["similar"],
        avg_gap_pct=k["avg_gap_pct"],
        vtr_freq_monthly_total=vtr_freq,
        vtr_avg_departures_per_month=round(vtr_freq / vtr_count, 1) if vtr_count else None,
        market_freq_monthly_total=k["market_freq_monthly"],
        freq_leading_segments=k["freq_leading"],
        freq_lagging_segments=k["freq_lagging"],
        methodology=METHODOLOGY,
    )
    try:
        redis_set(cache_key, result.model_dump(), ttl=300)
        # Persist default (no filter) to disk for next restart
        if no_filter:
            from persistent_cache import save_json
            save_json("compare_summary_default", result.model_dump(), ttl_hours=24)
    except Exception:  # noqa: BLE001
        pass
    return result


@router.get("/segments")
def compare_segments(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    sort_by: str = Query("gap_pct"),
    sort_dir: str = Query("desc"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Disk fast-path cho default (no filter) — tránh đợi 40s prewarm
    no_filter = not (thi_truong or tuyen_tour or diem_kh)
    rows: list[dict] | None = None
    if no_filter:
        from persistent_cache import load_json
        disk_rows = load_json("compare_segments_default", max_age_hours=24)
        if disk_rows:
            rows = list(disk_rows)

    if rows is None:
        ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh)
        rows = list(ctx.segment_rows)
        if no_filter:
            try:
                from persistent_cache import save_json
                save_json("compare_segments_default", rows, ttl_hours=24)
            except Exception:  # noqa: BLE001
                pass

    # raw getter (KHÔNG default -999/0) để phân biệt None thật → đẩy None xuống ĐÁY bất
    # kể chiều sort (trước đây None→-999 nên tuyến 'không tính được gap' nhảy lên đầu khi asc).
    _num_field = {
        "gap_pct": "gap_pct", "freq_gap_pct": "freq_gap_pct",
        "vietravel_avg": "vietravel_avg_day", "vietravel_avg_price": "vietravel_avg_price",
        "comparison_price": "comparison_price", "market_min_price": "market_min_price",
        "market_avg": "market_avg_day", "vietravel_freq": "vietravel_freq_monthly",
        "so_ngay": "so_ngay",
    }
    _str_field = {"thi_truong": "thi_truong", "tuyen_tour": "tuyen_tour", "diem_kh": "diem_kh"}
    reverse = sort_dir != "asc"
    if sort_by in _str_field:
        f = _str_field[sort_by]
        rows.sort(key=lambda r: (r.get(f) or ""), reverse=reverse)
    else:
        f = _num_field.get(sort_by, "gap_pct")

        def _k(r):
            v = r.get(f)
            if v is None:
                return (1, 0.0)  # None: nhóm sau cùng
            return (0, -v if reverse else v)

        rows.sort(key=_k)
    return {"methodology": METHODOLOGY, "items": rows[:limit], "total": len(rows)}


def _segment_detail_payload(seg) -> dict:
    by_company: dict[str, list] = defaultdict(list)
    for e in seg.entries:
        by_company[e.cong_ty].append({
            "id": e.tour_id,
            "ten_tour": e.ten_tour,
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "price_day": e.price_day,
            "freq_monthly": e.freq_score,
            "freq_label": e.freq_label,
            "lich_kh": e.lich_kh,
            "lich_trinh": e.lich_trinh[:300] if e.lich_trinh else "",
            "link_url": e.link_url,
            "thoi_gian": e.thoi_gian,
            "is_vietravel": e.is_vietravel,
        })

    companies = []
    for co, tours_list in sorted(by_company.items(), key=lambda x: (-len(x[1]), x[0])):
        companies.append({
            "cong_ty": co,
            "is_vietravel": is_vietravel(co),
            "tour_count": len(tours_list),
            "tours": sorted(tours_list, key=lambda t: t["price_day"]),
        })

    return {
        "found": True,
        "segment": seg.to_dict(),
        "companies": companies,
        "methodology": METHODOLOGY,
    }


@router.get("/segment-detail")
def segment_detail(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    seg = get_segment_by_key(db, key)
    if not seg:
        parsed = parse_segment_key(key)
        if parsed:
            market, route, depart = parsed
            ctx = get_compare_context(db, [market], route, depart, allow_stale=False)
            seg = ctx.segment_by_key.get(key)
    if not seg:
        return {"segment_key": key, "found": False}
    return _segment_detail_payload(seg)


@router.get("/segment-tours")
def segment_tours(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    seg = get_segment_by_key(db, key)
    if not seg:
        return {"segment_key": key, "tours": []}
    flat = []
    for e in seg.entries:
        flat.append({
            "id": e.tour_id,
            "cong_ty": e.cong_ty,
            "ten_tour": e.ten_tour,
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "price_day": e.price_day,
            "freq_monthly": e.freq_score,
            "lich_kh": e.lich_kh,
            "is_vietravel": e.is_vietravel,
        })
    flat.sort(key=lambda x: x["price_day"])
    return {"segment_key": key, "tours": flat, "segment": seg.to_dict()}


@router.get("/weekday-distribution")
def weekday_distribution(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Phân bổ đoàn KH theo thứ trong tuần — VTR vs thị trường."""
    from compare_engine import build_weekday_distribution

    no_filter = not (thi_truong or tuyen_tour or diem_kh)
    if no_filter:
        from persistent_cache import load_json
        _disk = load_json("compare_weekday_default", max_age_hours=24)
        if _disk is not None:
            return _disk
    # Cần ctx.tours (full) → không stale.
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False)
    result = build_weekday_distribution(ctx.tours)
    if no_filter:
        try:
            from persistent_cache import save_json
            save_json("compare_weekday_default", result, ttl_hours=24)
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/competitors")
def list_competitors(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Disk fast-path (no-filter, limit mặc định): tránh build đồng bộ 15-114s khi cold.
    no_filter = not (thi_truong or tuyen_tour or diem_kh) and limit == 30
    if no_filter:
        from persistent_cache import load_json
        _disk = load_json("compare_competitors_default", max_age_hours=24)
        if _disk is not None:
            return _disk

    # Cần ctx.segments (full) → không stale. Áp dụng đủ bộ lọc (tuyến + điểm KH) như
    # các tab khác — trước đây chỉ nhận thi_truong nên filter điểm KH bị bỏ qua.
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False)
    segments = ctx.segments
    stats: dict[str, dict] = {}
    company_routes: dict[str, set] = defaultdict(set)

    # Baseline giá/ngày VTR (cho thành phần "giá cạnh tranh" trong score) — avg có
    # trọng số theo tần suất, chỉ tính entry có ngày KH (freq_score>0).
    vtr_pd_num = vtr_pd_den = 0.0
    for seg in segments:
        for e in seg.vtr_entries:
            if e.freq_score > 0 and e.price_day:
                vtr_pd_num += e.price_day * e.freq_score
                vtr_pd_den += e.freq_score
    vtr_price_day_baseline = (vtr_pd_num / vtr_pd_den) if vtr_pd_den else 0.0

    for seg in segments:
        for e in seg.market_entries:
            co = resolve_company_name(e.cong_ty)
            if is_vietravel(co):
                continue
            if co not in stats:
                stats[co] = {
                    "cong_ty": co,
                    "overlap_segments": 0,
                    "freq_monthly": 0.0,
                    "pd_num": 0.0,   # giá/ngày có TRỌNG SỐ theo tần suất (khớp toàn hệ thống)
                    "pd_den": 0.0,
                }
            stats[co]["freq_monthly"] += e.freq_score
            if e.freq_score > 0 and e.price_day:
                stats[co]["pd_num"] += e.price_day * e.freq_score
                stats[co]["pd_den"] += e.freq_score

    # "Sản phẩm" = số CHƯƠNG TRÌNH (dedup ma_tour) đếm trên ctx.tours — CÙNG cơ sở với
    # total_tours của popup chi tiết → 2 nơi không lệch số. (Trước: đếm theo entry segment.)
    comp_prog: dict[str, set] = defaultdict(set)
    for t in ctx.tours:
        co = resolve_company_name(t.cong_ty)
        if is_vietravel(co):
            continue
        comp_prog[co].add((t.ma_tour or "").strip() or (t.ten_tour or "").strip())

    seg_companies: dict[str, set] = defaultdict(set)
    for seg in segments:
        for e in seg.entries:
            if not e.is_vietravel:
                co = resolve_company_name(e.cong_ty)
                seg_companies[co].add(seg.key)
                # Route key cho momentum lookup
                from market_lab_engine import make_route_key
                company_routes[co].add(make_route_key(seg.thi_truong, seg.tuyen_tour))

    # Market trend cho mỗi đối thủ — avg supply_delta_pct của các tuyến họ tham gia
    market_trend: dict[str, float | None] = {}
    try:
        from market_lab_cache import load_momentum_map
        momentum_map = load_momentum_map(db)
        for co, routes_set in company_routes.items():
            deltas = [momentum_map.get(rk, {}).get("supply_delta_pct") for rk in routes_set]
            deltas = [d for d in deltas if d is not None]
            market_trend[co] = round(sum(deltas) / len(deltas), 1) if deltas else None
    except Exception:
        pass

    rows = []
    for co, s in stats.items():
        avg_day = round(s["pd_num"] / s["pd_den"], 0) if s["pd_den"] else None
        rows.append({
            "cong_ty": co,
            "tour_count": len(comp_prog.get(co, set())),  # số chương trình (khớp popup detail)
            "overlap_segments": len(seg_companies.get(co, set())),
            "freq_monthly": round(s["freq_monthly"], 1),
            "avg_price_day": avg_day,
            "market_trend": market_trend.get(co),  # avg supply_delta_pct tuyến đang cạnh tranh
        })

    # ── Score "đối thủ nặng ký" (0–100) — chuẩn hoá min-max 4 thành phần rồi gia quyền:
    #   Nhóm trùng 35% (cạnh tranh trực diện) · Tần suất tổng 30% (quy mô) ·
    #   Số chương trình 15% (độ phủ SP) · Giá cạnh tranh 20% (rẻ hơn VTR = áp lực hơn).
    def _norm(vals: list[float]) -> dict:
        mx = max(vals) if vals else 0
        return {"max": mx}

    n_overlap = _norm([r["overlap_segments"] for r in rows])["max"] or 1
    n_freq = _norm([r["freq_monthly"] for r in rows])["max"] or 1
    n_prod = _norm([r["tour_count"] for r in rows])["max"] or 1
    for r in rows:
        # Giá cạnh tranh: baseline VTR / giá ĐT. >1 = ĐT rẻ hơn VTR → áp lực cao. Clamp 0..1.
        if vtr_price_day_baseline and r["avg_price_day"]:
            ratio = vtr_price_day_baseline / r["avg_price_day"]
            price_aggr = max(0.0, min(1.0, (ratio - 0.7) / 0.6))  # 0.7→0, 1.3→1
        else:
            price_aggr = 0.0
        score = 100 * (
            0.35 * (r["overlap_segments"] / n_overlap)
            + 0.30 * (r["freq_monthly"] / n_freq)
            + 0.15 * (r["tour_count"] / n_prod)
            + 0.20 * price_aggr
        )
        r["score"] = round(score, 1)

    rows.sort(key=lambda x: (-x["score"], -x["overlap_segments"]))
    result = {"items": rows[:limit], "total": len(rows)}
    if no_filter:
        try:
            from persistent_cache import save_json
            save_json("compare_competitors_default", result, ttl_hours=24)
        except Exception:  # noqa: BLE001
            pass
    return result


@router.get("/competitor")
def competitor_detail(
    company: str = Query(..., description="Tên công ty (canonical) — query param tránh lỗi 404 khi tên có ký tự / & …"),
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Cần ctx.tours (full) → không stale. Áp dụng đủ bộ lọc cho khớp bảng list.
    ctx = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False)
    # Tái dùng segments + tours (đã dedup) trong ctx — khỏi rebuild (~874ms/lần).
    return build_competitor_overview(ctx.tours, company, segments=ctx.segments, tours_dedup=ctx.tours)
