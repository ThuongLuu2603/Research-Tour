from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from database import engine

logger = logging.getLogger(__name__)


def _migrate_tour_columns():
    insp = inspect(engine)
    if "tours" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("tours")}
    alters = []
    if "external_id" not in cols:
        alters.append("ADD COLUMN external_id VARCHAR(128) DEFAULT ''")
    if "sheet_source" not in cols:
        alters.append("ADD COLUMN sheet_source VARCHAR(64) DEFAULT ''")
    if "sheet_row" not in cols:
        alters.append("ADD COLUMN sheet_row INTEGER")
    if "content_hash" not in cols:
        alters.append("ADD COLUMN content_hash VARCHAR(64) DEFAULT ''")
    if "last_synced_at" not in cols:
        alters.append("ADD COLUMN last_synced_at TIMESTAMP")
    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(f"ALTER TABLE tours {stmt}"))
            except Exception as e:
                logger.warning("tour migration skipped (%s): %s", stmt, e)


def _migrate_saved_views():
    insp = inspect(engine)
    if "saved_views" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("saved_views")}
    if "workspace_id" in cols:
        return
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE saved_views ADD COLUMN workspace_id INTEGER"))
        except Exception as e:
            logger.warning("saved_views migration skipped: %s", e)


def _backfill_external_ids(batch_size: int = 500) -> None:
    from database import SessionLocal
    from models import Tour
    from tour_identity import compute_external_id

    db = SessionLocal()
    try:
        used: set[str] = {
            r[0]
            for r in db.query(Tour.external_id).filter(Tour.external_id != "").all()
            if r[0]
        }
        updated = 0
        while True:
            batch = (
                db.query(Tour)
                .filter((Tour.external_id == "") | (Tour.external_id.is_(None)))
                .limit(batch_size)
                .all()
            )
            if not batch:
                break
            for tour in batch:
                ext = compute_external_id(
                    tour.nguon or tour.sheet_source or "Unknown",
                    ma_tour=tour.ma_tour,
                    link_url=tour.link_url,
                    ten_tour=tour.ten_tour,
                )
                if ext in used:
                    ext = f"{ext}:id{tour.id}"
                tour.external_id = ext[:128]
                if not tour.sheet_source:
                    tour.sheet_source = tour.nguon or ""
                used.add(tour.external_id)
                updated += 1
            db.commit()
            db.expunge_all()
        if updated:
            logger.info("Backfilled external_id for %s tours", updated)
    finally:
        db.close()


def _ensure_default_workspaces():
    from database import SessionLocal
    from models import User
    from workspace_service import ensure_personal_workspace

    db = SessionLocal()
    try:
        for user in db.query(User).all():
            ensure_personal_workspace(db, user)
    finally:
        db.close()
