"""In-memory cache for compare engine — tránh load + tính lại toàn bộ tour mỗi request."""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from compare_engine import SegmentStats, build_segment_stats, deduplicate_tours
from models import Tour
from tour_sources import apply_market_compare_source_filter, filter_tours_for_market_compare

logger = logging.getLogger(__name__)

# TTL dài (6h) — KHÔNG rebuild định kỳ. Việc rebuild do FINGERPRINT (đổi dữ liệu) + invalidate
# sau mỗi sync quyết định. Tránh quét lại toàn bộ ~8000 tour mỗi 15' (giảm RU + bớt Slow Execution).
TTL_SECONDS = int(os.getenv("COMPARE_CACHE_TTL", "21600"))
# Fingerprint (count + max(updated_at)) cũng quét bảng → cache lâu hơn (10') để bớt query.
# An toàn: mọi thay đổi qua sync đều gọi invalidate_compare_cache (xoá luôn fingerprint).
_FINGERPRINT_TTL = int(os.getenv("COMPARE_FINGERPRINT_TTL", "600"))


def _segments_to_rows(segments: list[SegmentStats]) -> list[dict]:
    rows: list[dict] = []
    for seg in segments:
        try:
            rows.append(seg.to_dict())
        except Exception as e:
            logger.warning("segment to_dict failed key=%s: %s", seg.key, e)
    return rows


@dataclass
class CompareContext:
    tours: list[Tour]
    segments: list[SegmentStats]
    segment_by_key: dict[str, SegmentStats]
    segment_rows: list[dict] = field(default_factory=list)


_lock = threading.Lock()
_cache: dict[tuple, tuple[float, CompareContext]] = {}
_fingerprint_cache: tuple[float, tuple[int, str | None]] | None = None
_inflight: dict[tuple, threading.Event] = {}


def _redis_key_for(key: tuple) -> str:
    """Convert in-memory cache key tuple → Redis key string."""
    from redis_cache import make_key
    markets, tuyen, diem, fp = key
    return make_key("compare", markets=list(markets), tuyen=tuyen, diem=diem, fp_count=fp[0], fp_updated=fp[1])


def _save_to_redis(key: tuple, ctx: CompareContext) -> None:
    """Persist segment_rows ra Redis. Tour/Segment ORM không serialize được, chỉ rows."""
    try:
        from redis_cache import redis_set

        redis_set(_redis_key_for(key), {"segment_rows": ctx.segment_rows}, ttl=TTL_SECONDS)
    except Exception as e:  # noqa: BLE001
        logger.debug("Redis persist skipped: %s", e)


def _load_from_redis(key: tuple) -> CompareContext | None:
    """Khôi phục lightweight CompareContext từ Redis (chỉ segment_rows).
    Caller nào cần tours/segments/segment_by_key phải rebuild — trả về None segments để force rebuild.
    Caller dùng segment_rows (vd API /compare/segments) sẽ hit ngay."""
    try:
        from redis_cache import redis_get

        data = redis_get(_redis_key_for(key))
        if not data or "segment_rows" not in data:
            return None
        rows = data["segment_rows"]
        if not isinstance(rows, list):
            return None
        logger.info("Compare cache: restored %d segment_rows from Redis", len(rows))
        return CompareContext(
            tours=[],
            segments=[],
            segment_by_key={},
            segment_rows=rows,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("Redis load skipped: %s", e)
        return None


def _db_fingerprint(db: Session) -> tuple[int, str | None]:
    global _fingerprint_cache
    now = time.time()
    if _fingerprint_cache and now - _fingerprint_cache[0] < _FINGERPRINT_TTL:
        return _fingerprint_cache[1]
    row = (
        apply_market_compare_source_filter(
            db.query(func.count(Tour.id), func.max(Tour.updated_at)).filter(
                Tour.gia != None, Tour.gia > 0  # noqa: E711
            )
        ).one()
    )
    fp = (int(row[0] or 0), row[1].isoformat() if row[1] else None)
    _fingerprint_cache = (now, fp)
    return fp


def _cache_key(thi_truong: list[str], tuyen_tour: str, diem_kh: str, fp: tuple[int, str | None]) -> tuple:
    return (tuple(sorted(thi_truong)), tuyen_tour.strip(), diem_kh.strip(), fp)


def _has_filters(thi_truong: list[str], tuyen_tour: str, diem_kh: str) -> bool:
    return bool(thi_truong or tuyen_tour.strip() or diem_kh.strip())


def _filter_tours(
    tours: list[Tour],
    thi_truong: list[str],
    tuyen_tour: str,
    diem_kh: str,
) -> list[Tour]:
    out = tours
    if thi_truong:
        markets = {m.strip() for m in thi_truong}
        out = [t for t in out if (t.thi_truong or "").strip() in markets]
    if tuyen_tour.strip():
        needle = tuyen_tour.strip().lower()
        out = [t for t in out if needle in (t.tuyen_tour or "").lower()]
    if diem_kh.strip():
        needle = diem_kh.strip().lower()
        out = [t for t in out if needle in (t.diem_kh or "").lower()]
    return out


def _filter_context(
    base: CompareContext,
    thi_truong: list[str],
    tuyen_tour: str,
    diem_kh: str,
) -> CompareContext:
    """Lọc từ cache gốc (toàn thị trường) — tránh load DB + build_segment_stats lại."""
    segments = base.segments
    if thi_truong:
        markets = set(thi_truong)
        segments = [s for s in segments if s.thi_truong in markets]
    if tuyen_tour.strip():
        needle = tuyen_tour.strip().lower()
        segments = [s for s in segments if needle in (s.tuyen_tour or "").lower()]
    if diem_kh.strip():
        needle = diem_kh.strip().lower()
        segments = [s for s in segments if needle in (s.diem_kh or "").lower()]
    tours = _filter_tours(base.tours, thi_truong, tuyen_tour, diem_kh)
    segment_rows = _segments_to_rows(segments)
    return CompareContext(
        tours=tours,
        segments=segments,
        segment_by_key={s.key: s for s in segments},
        segment_rows=segment_rows,
    )


def load_tours(
    db: Session,
    thi_truong: list[str],
    tuyen_tour: str = "",
    diem_kh: str = "",
) -> list[Tour]:
    """Load chỉ cột cần cho compare engine — giảm Egress đáng kể.
    Các cột dùng bởi compare_engine: id, cong_ty, ten_tour, lich_trinh, thi_truong,
    tuyen_tour, diem_kh, gia, gia_raw, thoi_gian, so_ngay, lich_kh, link_url,
    ma_tour, nguon, updated_at.
    """
    from sqlalchemy.orm import load_only

    q = apply_market_compare_source_filter(
        db.query(Tour)
        .options(load_only(
            Tour.id,
            Tour.cong_ty,
            Tour.ten_tour,
            Tour.lich_trinh,
            Tour.thi_truong,
            Tour.tuyen_tour,
            Tour.diem_kh,
            Tour.gia,
            Tour.gia_raw,
            Tour.thoi_gian,
            Tour.so_ngay,
            Tour.lich_kh,
            Tour.link_url,
            Tour.ma_tour,
            Tour.nguon,
            Tour.updated_at,
            Tour.sheet_source,  # cần cho is_vietravel_tab() — thiếu gây lazy-load 8000+ lần
            Tour.phan_khuc,     # cần cho segment stats (phía thị trường: Premium)
            Tour.dong_tour,     # Dòng tour VTR (Tiết kiệm/Giá Tốt…) — lọc giá phía Vietravel
            Tour.flagged,       # cần cho compute_data_quality() trong Báo cáo BGĐ —
                                # thiếu gây DetachedInstanceError khi cache trả tour cho session khác
        ))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
    )
    # System-wide rule: loại trừ market "Không xác định" khỏi mọi calculation.
    from tour_filters import market_filter_clause
    q = q.filter(market_filter_clause(Tour))
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        needle = tuyen_tour.strip()
        q = q.filter(
            or_(
                Tour.tuyen_tour == needle,
                Tour.tuyen_tour.ilike(f"%{needle}%"),
            )
        )
    if diem_kh:
        needle = diem_kh.strip()
        q = q.filter(
            or_(
                Tour.diem_kh == needle,
                Tour.diem_kh.ilike(f"%{needle}%"),
            )
        )
    return filter_tours_for_market_compare(q.all())


def _build_context(db: Session, thi_truong: list[str], tuyen_tour: str, diem_kh: str) -> CompareContext:
    t0 = time.time()
    raw = load_tours(db, thi_truong, tuyen_tour, diem_kh)
    tours = deduplicate_tours(raw)
    segments = build_segment_stats(tours, dedup=False)
    segment_rows = _segments_to_rows(segments)
    logger.info(
        "Built compare context filters=%s/%s/%s tours=%s segments=%s in %.1fs",
        thi_truong, tuyen_tour, diem_kh, len(tours), len(segments), time.time() - t0,
    )
    return CompareContext(
        tours=tours,
        segments=segments,
        segment_by_key={s.key: s for s in segments},
        segment_rows=segment_rows,
    )


def get_compare_context(
    db: Session,
    thi_truong: list[str],
    tuyen_tour: str = "",
    diem_kh: str = "",
) -> CompareContext:
    fp = _db_fingerprint(db)
    key = _cache_key(thi_truong, tuyen_tour, diem_kh, fp)
    now = time.time()

    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]
        if _has_filters(thi_truong, tuyen_tour, diem_kh):
            base_key = _cache_key([], "", "", fp)
            base_hit = _cache.get(base_key)
            if base_hit and now - base_hit[0] < TTL_SECONDS:
                filtered = _filter_context(base_hit[1], thi_truong, tuyen_tour, diem_kh)
                _cache[key] = (now, filtered)
                return filtered
        # In-memory MISS — thử Redis trước khi rebuild từ DB.
        # Chỉ áp dụng cho lookup không filter (base context) — filter caller có thể tự
        # filter trên rows nhưng rebuild trên DB ở đây cũng nhanh nếu base có sẵn.
        if not _has_filters(thi_truong, tuyen_tour, diem_kh):
            restored = _load_from_redis(key)
            if restored is not None:
                _cache[key] = (now, restored)
                return restored
        if key in _inflight:
            waiter = _inflight[key]
            is_owner = False
        else:
            waiter = threading.Event()
            _inflight[key] = waiter
            is_owner = True

    if not is_owner:
        waiter.wait(timeout=300)
        with _lock:
            hit = _cache.get(key)
            if hit:
                return hit[1]
        # Builder failed or timed out — try once more as owner
        return get_compare_context(db, thi_truong, tuyen_tour, diem_kh)

    try:
        if _has_filters(thi_truong, tuyen_tour, diem_kh):
            base_ctx = _build_context(db, [], "", "")
            ctx = _filter_context(base_ctx, thi_truong, tuyen_tour, diem_kh)
            with _lock:
                _cache[_cache_key([], "", "", fp)] = (time.time(), base_ctx)
        else:
            ctx = _build_context(db, thi_truong, tuyen_tour, diem_kh)
        with _lock:
            _cache[key] = (time.time(), ctx)
            if len(_cache) > 32:
                oldest = min(_cache.items(), key=lambda x: x[1][0])[0]
                _cache.pop(oldest, None)
        # Persist segment_rows ra Redis — survive backend restart.
        _save_to_redis(key, ctx)
        return ctx
    finally:
        with _lock:
            ev = _inflight.pop(key, None)
            if ev:
                ev.set()


def get_segment_by_key(db: Session, key: str) -> SegmentStats | None:
    ctx = get_compare_context(db, [], "", "")
    return ctx.segment_by_key.get(key)


def invalidate_compare_cache() -> None:
    global _fingerprint_cache
    with _lock:
        _cache.clear()
        for ev in _inflight.values():
            ev.set()
        _inflight.clear()
    _fingerprint_cache = None
    # Cũng xoá Redis — tránh trả data cũ sau khi sync.
    try:
        from redis_cache import redis_invalidate_pattern

        n = redis_invalidate_pattern("ota:compare:*")
        if n > 0:
            logger.info("Compare cache: invalidated %d Redis keys", n)
    except Exception as e:  # noqa: BLE001
        logger.debug("Redis invalidate skipped: %s", e)
    try:
        from api_cache import invalidate_api_read_cache
        invalidate_api_read_cache()
    except Exception:
        pass
    try:
        from market_lab_cache import invalidate_market_lab_cache
        invalidate_market_lab_cache()
    except Exception:
        pass


def prewarm_compare_cache(db: Session) -> None:
    """Build default compare context after sync/scrape to avoid cold-request timeouts."""
    logger.info("Pre-warming compare cache...")
    get_compare_context(db, [], "", "")
    logger.info("Compare cache pre-warm complete")
    try:
        from market_lab_cache import prewarm_market_lab_cache
        prewarm_market_lab_cache(db)
    except Exception as e:
        logger.warning("Market Lab prewarm after compare: %s", e)
