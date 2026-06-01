from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

_url = settings.database_url
_is_sqlite = _url.startswith("sqlite")
_is_postgres = _url.startswith("postgresql")

connect_args: dict = {}
engine_kwargs: dict = {}

if _is_sqlite:
    connect_args = {"check_same_thread": False}
elif _is_postgres:
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_size": 5,
        "max_overflow": 10,
    }

engine = create_engine(_url, connect_args=connect_args, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

if _is_postgres and "supabase" in _url:
    import logging

    _db_log = logging.getLogger(__name__)
    if "pooler.supabase.com" in _url:
        _db_log.info("Supabase: using pooler connection (IPv4-friendly)")
    elif "@db." in _url:
        _db_log.warning(
            "Supabase direct host (db.*.supabase.co) may fail on Render (no IPv6). "
            "Set DATABASE_POOLER_URL from Dashboard → Session pooler."
        )


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create tables and apply lightweight schema migrations only (fast — safe before /health)."""
    from models import Tour, ScrapeJob, User, MarketKeywordRule, RouteKeywordRule, CompanyAliasRule, DepartureAliasRule, DurationAliasRule  # noqa: F401
    from models import DailySnapshot, SegmentSnapshot, RouteDailyMetrics, IntelAlert, SavedView, Workspace, WorkspaceMember, TourOverride  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_users_columns()
    from migrations import _migrate_tour_columns, _migrate_saved_views
    _migrate_tour_columns()
    _migrate_saved_views()


def run_deferred_db_maintenance() -> None:
    """Heavy one-off / batch work — run in background after app is up."""
    from migrations import _backfill_external_ids, _ensure_default_workspaces

    try:
        _backfill_external_ids()
        _ensure_default_workspaces()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Deferred DB maintenance failed: %s", e)
    try:
        from data_sources import SHEET_ONLY_NGUON
        from sheets_tour_sync import purge_nguon_from_db

        db = SessionLocal()
        try:
            for nguon in SHEET_ONLY_NGUON:
                purge_nguon_from_db(db, nguon)
        finally:
            db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Purge sheet-only tours failed: %s", e)
    try:
        from classification import seed_market_rules_from_hardcode
        seed_market_rules_from_hardcode()
    except Exception:
        pass


def _migrate_users_columns():
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    alters = []
    if "role" not in cols:
        alters.append("ADD COLUMN role VARCHAR(32) DEFAULT 'analyst'")
    if "avatar_url" not in cols:
        alters.append("ADD COLUMN avatar_url VARCHAR(512) DEFAULT ''")
    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(f"ALTER TABLE users {stmt}"))
            except Exception:
                pass
        conn.execute(text("UPDATE users SET role = 'admin' WHERE username = 'admin' AND (role IS NULL OR role = '' OR role = 'analyst')"))
