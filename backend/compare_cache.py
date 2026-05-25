"""In-memory cache for compare engine — tránh load + tính lại toàn bộ tour mỗi request."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock

from sqlalchemy import func
from sqlalchemy.orm import Session

from compare_engine import SegmentStats, build_segment_stats, deduplicate_tours
from models import Tour

logger = logging.getLogger(__name__)

TTL_SECONDS = 120


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


_lock = Lock()
_cache: dict[tuple, tuple[float, CompareContext]] = {}
_fingerprint_cache: tuple[float, tuple[int, str | None]] | None = None


def _db_fingerprint(db: Session) -> tuple[int, str | None]:
    global _fingerprint_cache
    now = time.time()
    if _fingerprint_cache and now - _fingerprint_cache[0] < 15:
        return _fingerprint_cache[1]
    row = (
        db.query(func.count(Tour.id), func.max(Tour.updated_at))
        .filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        .one()
    )
    fp = (int(row[0] or 0), row[1].isoformat() if row[1] else None)
    _fingerprint_cache = (now, fp)
    return fp


def _cache_key(thi_truong: list[str], tuyen_tour: str, diem_kh: str, fp: tuple[int, str | None]) -> tuple:
    return (tuple(sorted(thi_truong)), tuyen_tour.strip(), diem_kh.strip(), fp)


def load_tours(
    db: Session,
    thi_truong: list[str],
    tuyen_tour: str = "",
    diem_kh: str = "",
) -> list[Tour]:
    q = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.ilike(f"%{tuyen_tour}%"))
    if diem_kh:
        q = q.filter(Tour.diem_kh.ilike(f"%{diem_kh}%"))
    return q.all()


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

    raw = load_tours(db, thi_truong, tuyen_tour, diem_kh)
    tours = deduplicate_tours(raw)
    segments = build_segment_stats(tours, dedup=False)
    segment_rows = _segments_to_rows(segments)
    ctx = CompareContext(
        tours=tours,
        segments=segments,
        segment_by_key={s.key: s for s in segments},
        segment_rows=segment_rows,
    )

    with _lock:
        _cache[key] = (now, ctx)
        if len(_cache) > 32:
            oldest = min(_cache.items(), key=lambda x: x[1][0])[0]
            _cache.pop(oldest, None)

    return ctx


def get_segment_by_key(db: Session, key: str) -> SegmentStats | None:
    ctx = get_compare_context(db, [], "", "")
    return ctx.segment_by_key.get(key)


def invalidate_compare_cache() -> None:
    global _fingerprint_cache
    with _lock:
        _cache.clear()
    _fingerprint_cache = None


def prewarm_compare_cache(db: Session) -> None:
    """Build default compare context after sync/scrape to avoid cold-request timeouts."""
    get_compare_context(db, [], "", "")
