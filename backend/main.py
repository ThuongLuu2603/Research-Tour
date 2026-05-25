from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from api import auth, tours, analytics, scraper as scraper_api, admin, compare, rules as rules_api, intelligence as intelligence_api, workspaces
from api.scraper import set_event_loop
from database import init_db
from scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    init_db()
    from seed import create_default_users, start_import_background

    create_default_users()
    start_import_background()

    def _snapshot_bg() -> None:
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

    threading.Thread(target=_snapshot_bg, daemon=True, name="daily-snapshot").start()

    def _prewarm_after_import() -> None:
        import time
        from seed import get_import_status
        for _ in range(180):
            if not get_import_status().get("running"):
                break
            time.sleep(2)
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

    threading.Thread(target=_prewarm_after_import, daemon=True, name="compare-prewarm").start()
    set_event_loop(asyncio.get_event_loop())
    start_scheduler()
    logger.info("OTA Research Platform started")
    yield
    # Shutdown
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

# API routers
app.include_router(auth.router)
app.include_router(tours.router)
app.include_router(analytics.router)
app.include_router(scraper_api.router)
app.include_router(admin.router)
app.include_router(compare.router)
app.include_router(rules_api.router)
app.include_router(intelligence_api.router)
app.include_router(workspaces.router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Serve React build (production)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        index = FRONTEND_DIR / "index.html"
        return FileResponse(str(index))
