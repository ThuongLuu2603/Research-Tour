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
    if "dong_tour" not in cols:
        alters.append("ADD COLUMN dong_tour VARCHAR(64) DEFAULT ''")
    if "manual_locked" not in cols:
        alters.append("ADD COLUMN manual_locked BOOLEAN DEFAULT FALSE")
    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(f"ALTER TABLE tours {stmt}"))
            except Exception as e:
                logger.warning("tour migration skipped (%s): %s", stmt, e)


def _migrate_scrape_jobs_columns():
    insp = inspect(engine)
    if "scrape_jobs" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("scrape_jobs")}
    if "heartbeat_at" in cols:
        return
    with engine.begin() as conn:
        try:
            conn.execute(text("ALTER TABLE scrape_jobs ADD COLUMN heartbeat_at TIMESTAMP"))
        except Exception as e:
            logger.warning("scrape_jobs heartbeat_at migration skipped: %s", e)


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


_FK_SET_NULL_FLAG = "fk_classification_rule_id_set_null_v1"


def _migrate_classification_rule_fk_set_null():
    """Đổi FK tours.classification_rule_id sang ON DELETE SET NULL.

    Trước: xóa rule → tours đang reference bị FK violation, apply worker crash với
    ForeignKeyViolation (Render log 2026-06-07 11:34). Sau migration: DB tự set NULL
    khi rule bị xóa, không cần pre-clean trong API endpoint nữa.

    Chỉ chạy trên PostgreSQL/CockroachDB. Gated bằng flag để không re-issue schema
    change mỗi lần deploy."""
    if not _is_postgres():
        return
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            done = conn.execute(
                text("SELECT 1 FROM app_kv WHERE key = :k"), {"k": _FK_SET_NULL_FLAG}
            ).first()
        if done:
            return
    except Exception:  # noqa: BLE001
        return

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            # Drop old constraint, add new with ON DELETE SET NULL.
            # CockroachDB cho phép trong cùng schema change job.
            conn.execute(text("ALTER TABLE tours DROP CONSTRAINT IF EXISTS tours_classification_rule_id_fkey"))
            conn.execute(text(
                "ALTER TABLE tours ADD CONSTRAINT tours_classification_rule_id_fkey "
                "FOREIGN KEY (classification_rule_id) REFERENCES route_keyword_rules(id) "
                "ON DELETE SET NULL"
            ))
        logger.info("FK tours.classification_rule_id → ON DELETE SET NULL applied")
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(
                    "INSERT INTO app_kv (key, value_json, updated_at) "
                    "VALUES (:k, '\"done\"', NOW()) ON CONFLICT (key) DO NOTHING"
                ),
                {"k": _FK_SET_NULL_FLAG},
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("FK SET NULL migration skipped (sẽ thử lại lần deploy sau): %s", e)


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


def _is_postgres() -> bool:
    from config import settings

    return settings.database_url.startswith("postgresql")


def _migrate_tour_search_columns():
    insp = inspect(engine)
    if "tours" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("tours")}
    alters = []
    if "search_text" not in cols:
        alters.append("ADD COLUMN search_text TEXT DEFAULT ''")
    if "search_text_folded" not in cols:
        alters.append("ADD COLUMN search_text_folded TEXT DEFAULT ''")
    if "segment_key" not in cols:
        alters.append("ADD COLUMN segment_key VARCHAR(512) DEFAULT ''")
    if "classification_rule_id" not in cols:
        alters.append("ADD COLUMN classification_rule_id INTEGER")
    if "classified_at" not in cols:
        alters.append("ADD COLUMN classified_at TIMESTAMP")
    with engine.begin() as conn:
        for stmt in alters:
            try:
                conn.execute(text(f"ALTER TABLE tours {stmt}"))
            except Exception as e:
                logger.warning("tour search column migration skipped (%s): %s", stmt, e)
        if _is_postgres() and "search_tsv" not in cols:
            try:
                conn.execute(text("ALTER TABLE tours ADD COLUMN search_tsv tsvector"))
            except Exception as e:
                logger.warning("search_tsv column skipped: %s", e)


_SEARCH_IDX_FLAG = "search_indexes_v2"


def _migrate_search_indexes():
    if not _is_postgres():
        return
    # Chạy 1 LẦN — tránh re-issue job CREATE INDEX (schema change) mỗi lần deploy, gây pileup
    # + tranh chấp với sync trên bảng tours. (Bump _SEARCH_IDX_FLAG khi thêm index mới.)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            done = conn.execute(
                text("SELECT 1 FROM app_kv WHERE key = :k"), {"k": _SEARCH_IDX_FLAG}
            ).first()
        if done:
            return
    except Exception:
        pass
    stmts = [
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_search_gin
        ON tours USING GIN (search_tsv)
        """,
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_canonical_priced
        ON tours (nguon, thi_truong, tuyen_tour)
        WHERE gia IS NOT NULL AND gia > 0
        """,
        # Index THƯỜNG (không UNIQUE): có dòng trùng (nguon, external_id) trong DB nên UNIQUE
        # tạo FAIL liên tục → mỗi deploy lại rollback + đẻ job GC. Sync khớp tour bằng SELECT,
        # không cần ràng buộc unique. Dùng tên mới để không đụng index cũ đang rollback.
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_nguon_extid
        ON tours (nguon, external_id)
        WHERE external_id IS NOT NULL AND external_id <> ''
        """,
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_empty_route
        ON tours (nguon, id)
        WHERE tuyen_tour IS NULL OR trim(tuyen_tour) = ''
        """,
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_list_sort
        ON tours (nguon, updated_at DESC, id)
        """,
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_segment_key
        ON tours (segment_key)
        WHERE segment_key IS NOT NULL AND segment_key <> ''
        """,
        # fingerprint query (count + max updated_at) chạy mỗi 60s
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_fingerprint
        ON tours (updated_at DESC)
        WHERE gia IS NOT NULL AND gia > 0
        """,
        # compare/market-lab GROUP BY thị trường × tuyến
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_market_route_price
        ON tours (thi_truong, tuyen_tour, gia)
        WHERE gia IS NOT NULL AND gia > 0
        """,
        # stale job detection
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_scrape_jobs_status_started
        ON scrape_jobs (status, started_at DESC)
        """,
        # classify incremental: tour chưa qua apply
        """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tours_classify_pending
        ON tours (id)
        WHERE classified_at IS NULL
        """,
    ]
    for stmt in stmts:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(stmt))
        except Exception as e:
            logger.warning("index migration skipped: %s", e)
    # Đánh dấu đã chạy → các deploy sau bỏ qua (không tạo thêm schema-change job).
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(
                text(
                    # updated_at NOT NULL — phải supply explicitly vì raw SQL bypass
                    # SQLAlchemy default=datetime.utcnow ở model _AppKV.
                    "INSERT INTO app_kv (key, value_json, updated_at) "
                    "VALUES (:k, '\"done\"', NOW()) "
                    "ON CONFLICT (key) DO NOTHING"
                ),
                {"k": _SEARCH_IDX_FLAG},
            )
    except Exception as e:
        logger.warning("mark search indexes done skipped: %s", e)


def run_search_migrations(*, create_indexes: bool = False) -> None:
    """Cột + MV — indexes nặng, chạy deferred."""
    _migrate_tour_search_columns()
    if _is_postgres():
        try:
            # MV vô dụng + REFRESH treo trên CockroachDB → DROP để dọn các job REFRESH/GC đang kẹt.
            from segment_mv import drop_materialized_view

            drop_materialized_view()
        except Exception as e:
            logger.warning("drop segment MV skipped: %s", e)
    if create_indexes:
        _migrate_search_indexes()


def _backfill_tour_search_fields(batch_size: int = 500) -> None:
    from tour_search import backfill_search_columns

    stats = backfill_search_columns(batch_size=batch_size)
    logger.info("Backfill tour search fields: %s", stats)


def run_deferred_search_setup() -> None:
    """Chạy sau khi app đã listen — indexes GIN + backfill (chỉ PostgreSQL)."""
    run_search_migrations(create_indexes=True)
    try:
        _backfill_tour_search_fields()
    except Exception as e:
        logger.warning("search backfill skipped: %s", e)
    # (đã bỏ refresh_segment_mv — MV không còn dùng)
    try:
        from route_rule_tokens import rebuild_route_rule_tokens
        from database import SessionLocal

        db = SessionLocal()
        try:
            rebuild_route_rule_tokens(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning("route_rule_tokens skipped: %s", e)
