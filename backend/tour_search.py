"""Tìm kiếm tour — Full-Text Search PostgreSQL (GIN), không dịch vụ trả phí."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, text
from sqlalchemy.orm import Query, Session

from config import settings
from database import SessionLocal, engine

if TYPE_CHECKING:
    from models import Tour

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


def is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


def build_search_text(
    *,
    ten_tour: str = "",
    lich_trinh: str = "",
    cong_ty: str = "",
    ma_tour: str = "",
) -> str:
    parts = [ten_tour, lich_trinh, cong_ty, ma_tour]
    joined = " ".join(p.strip() for p in parts if p and str(p).strip())
    return _WHITESPACE.sub(" ", joined.lower())[:8000]


def compute_segment_key(tour: Tour) -> str:
    try:
        from pricing_segments import bucket_key_for_tour

        return (bucket_key_for_tour(tour) or "")[:512]
    except Exception:
        return ""


def update_tour_derived_fields(tour: Tour) -> None:
    """Cập nhật search_text + segment_key (tsvector qua SQL batch)."""
    tour.search_text = build_search_text(
        ten_tour=tour.ten_tour or "",
        lich_trinh=tour.lich_trinh or "",
        cong_ty=tour.cong_ty or "",
        ma_tour=tour.ma_tour or "",
    )
    tour.segment_key = compute_segment_key(tour)


def sync_search_tsv_for_ids(tour_ids: list[int]) -> None:
    """PostgreSQL: cập nhật search_tsv từ search_text."""
    if not tour_ids or not is_postgres():
        return
    ids = list({int(i) for i in tour_ids if i})
    if not ids:
        return
    try:
        with engine.begin() as conn:
            for i in range(0, len(ids), 200):
                chunk = ids[i : i + 200]
                placeholders = ", ".join(str(int(x)) for x in chunk)
                conn.execute(
                    text(
                        f"""
                        UPDATE tours
                        SET search_tsv = to_tsvector('simple', coalesce(search_text, ''))
                        WHERE id IN ({placeholders})
                        """
                    )
                )
    except Exception as e:
        logger.warning("sync_search_tsv failed: %s", e)


def after_tours_persisted(db: Session, tour_ids: list[int], *, deleted: bool = False) -> None:
    """Sau ghi tour — cập nhật GIN index (tsvector)."""
    _ = db, deleted
    if tour_ids:
        sync_search_tsv_for_ids(tour_ids)


def touch_tour_search(tour: Tour, db: Session | None = None) -> None:
    """Một tour vừa sửa — derived fields."""
    _ = db
    update_tour_derived_fields(tour)


def backfill_search_columns(batch_size: int = 500) -> dict:
    """Lần đầu deploy — search_text, segment_key, search_tsv."""
    from models import Tour

    db = SessionLocal()
    updated = 0
    last_id = 0
    try:
        while True:
            batch = (
                db.query(Tour)
                .filter(Tour.id > last_id)
                .order_by(Tour.id)
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            ids: list[int] = []
            for t in batch:
                update_tour_derived_fields(t)
                ids.append(t.id)
            db.commit()
            sync_search_tsv_for_ids(ids)
            updated += len(batch)
            last_id = batch[-1].id
        return {"updated": updated}
    finally:
        db.close()


def apply_search_filter(q: Query, search: str, *, use_rank: bool = False) -> Query:
    """Thay ILIKE full scan — FTS (PG) hoặc LIKE trên search_text (SQLite dev)."""
    from models import Tour

    term = (search or "").strip()
    if not term:
        return q
    if is_postgres():
        try:
            tsq = func.plainto_tsquery("simple", term)
            q = q.filter(text("tours.search_tsv @@ plainto_tsquery('simple', :q)").bindparams(q=term))
            if use_rank:
                q = q.order_by(func.ts_rank(text("tours.search_tsv"), tsq).desc())
            return q
        except Exception:
            pass
    like = f"%{term}%"
    return q.filter(
        or_(
            Tour.search_text.ilike(like),
            Tour.ten_tour.ilike(like),
            Tour.cong_ty.ilike(like),
            Tour.ma_tour.ilike(like),
        )
    )


def apply_keyword_prefilter(q: Query, keywords: list[str]) -> Query:
    """Lọc tour có thể khớp rule — FTS / search_text."""
    from models import Tour

    kws = [k.strip().lower() for k in keywords if k and str(k).strip()][:48]
    if not kws:
        return q
    if is_postgres():
        try:
            combined = " ".join(kws)
            return q.filter(
                text("tours.search_tsv @@ plainto_tsquery('simple', :q)").bindparams(q=combined)
            )
        except Exception:
            pass
    clauses = []
    for kw in kws:
        pat = f"%{kw}%"
        clauses.append(Tour.search_text.ilike(pat))
        clauses.append(Tour.ten_tour.ilike(pat))
        clauses.append(Tour.lich_trinh.ilike(pat))
    return q.filter(or_(*clauses))
