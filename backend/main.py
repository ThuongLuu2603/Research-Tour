from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from api import auth, tours, analytics, scraper as scraper_api, admin, compare, rules as rules_api, intelligence as intelligence_api, workspaces, market_lab as market_lab_api
from api.scraper import set_event_loop
from database import init_db, run_deferred_db_maintenance
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def _init_db_with_retry(*, max_attempts: int = 20, initial_wait: float = 20.0) -> None:
    import time

    from sqlalchemy.exc import OperationalError

    if initial_wait > 0:
        logger.info("init_db: chờ %.0fs để pool Supabase rảnh (deploy Render)...", initial_wait)
        time.sleep(initial_wait)

    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            init_db()
            return
        except OperationalError as e:
            last = e
            msg = str(e).lower()
            if "max clients" not in msg and "emaxconnsession" not in msg:
                raise
            wait = min(45, 5 + 2 ** attempt)
            logger.warning(
                "init_db: pool Supabase đầy, thử lại %s/%s sau %ss",
                attempt + 1,
                max_attempts,
                wait,
            )
            time.sleep(wait)
    if last:
        raise last


def _run_startup_maintenance() -> None:
    import time
    from seed import get_import_status

    time.sleep(5)
    try:
        from database import SessionLocal
        from scrape_job_utils import reconcile_stale_scrape_jobs

        db = SessionLocal()
        try:
            fixed = reconcile_stale_scrape_jobs(db)
            if fixed:
                logger.info("Reconciled %s stale scrape job(s): %s", len(fixed), fixed)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Stale scrape job reconcile skipped: %s", e)

    for _ in range(180):
        if not get_import_status().get("running"):
            break
        time.sleep(2)
    try:
        run_deferred_db_maintenance()
    except Exception as e:
        logger.warning("Deferred DB maintenance skipped: %s", e)
    try:
        from database import SessionLocal
        from compare_cache import prewarm_compare_cache

        db = SessionLocal()
        try:
            prewarm_compare_cache(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Compare pre-warm skipped: %s", e)


def _run_snapshot_bg() -> None:
    import time

    time.sleep(20)
    try:
        from database import SessionLocal
        from snapshot_service import capture_daily_snapshot

        db = SessionLocal()
        try:
            capture_daily_snapshot(db)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Initial snapshot skipped: %s", e)


def _bootstrap_database(app: FastAPI) -> None:
    import threading

    try:
        _init_db_with_retry()
        from seed import create_default_users, start_import_background

        create_default_users()
        start_import_background()
        app.state.db_ready = True
        threading.Thread(target=_run_startup_maintenance, daemon=True, name="startup-maintenance").start()
        threading.Thread(target=_run_snapshot_bg, daemon=True, name="daily-snapshot").start()
        start_scheduler()
        logger.info("Database bootstrap complete")
    except Exception:
        logger.exception(
            "Database bootstrap failed — kiểm tra DATABASE_POOLER_URL (nên dùng transaction pooler :6543)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    app.state.db_ready = False
    threading.Thread(
        target=_bootstrap_database,
        args=(app,),
        daemon=True,
        name="db-bootstrap",
    ).start()
    set_event_loop(asyncio.get_event_loop())
    logger.info("OTA Research Platform listening (DB bootstrap in background)")
    yield
    stop_scheduler()
    logger.info("OTA Research Platform stopped")


app = FastAPI(title="OTA Research Platform", version="1.0.0", lifespan=lifespan)

_origins = ["http://localhost:5173", "http://localhost:3000"]
if os.getenv("FRONTEND_URL"):
    _origins.append(os.environ["FRONTEND_URL"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(tours.router)
app.include_router(analytics.router)
app.include_router(scraper_api.router)
app.include_router(admin.router)
app.include_router(compare.router)
app.include_router(rules_api.router)
app.include_router(intelligence_api.router)
app.include_router(workspaces.router)
app.include_router(market_lab_api.router)


@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
def health(request: Request):
    """GET/HEAD for Render health check — HEAD luôn 200 kể cả DB đang bootstrap."""
    if request.method == "HEAD":
        return Response(status_code=200)
    ready = bool(getattr(request.app.state, "db_ready", False))
    return {"status": "ok", "db_ready": ready}


FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = FRONTEND_DIR / "index.html"
        return FileResponse(str(index))
