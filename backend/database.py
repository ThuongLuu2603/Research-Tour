from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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
    # Alias công ty / điểm KH / thời gian: chỉ cấu hình qua Quy tắc vận hành (không auto-seed hardcode).
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
