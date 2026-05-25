from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_schedule_hour = 7
_schedule_minute = 0


def get_schedule_config() -> dict:
    return {"hour": _schedule_hour, "minute": _schedule_minute, "enabled": _scheduler is not None}


def update_schedule_config(hour: int, minute: int):
    global _schedule_hour, _schedule_minute
    _schedule_hour = hour
    _schedule_minute = minute
    if _scheduler:
        _scheduler.reschedule_job("daily_vietravel", trigger=CronTrigger(hour=hour, minute=minute))
        _scheduler.reschedule_job("daily_findtourgo", trigger=CronTrigger(hour=hour, minute=minute + 20))
    logger.info("Schedule updated to %02d:%02d", hour, minute)


async def _auto_scrape(scraper_name: str):
    """Called by scheduler — runs in same process as FastAPI."""
    from database import SessionLocal
    from models import ScrapeJob
    from api.scraper import _run_job

    db = SessionLocal()
    try:
        job = ScrapeJob(
            scraper_name=scraper_name,
            status="pending",
            triggered_by="scheduler",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    import threading
    t = threading.Thread(target=_run_job, args=(job_id, scraper_name), daemon=True)
    t.start()
    logger.info("Auto-scrape triggered: %s job_id=%d", scraper_name, job_id)


async def _daily_snapshot():
    from database import SessionLocal
    from snapshot_service import capture_daily_snapshot
    db = SessionLocal()
    try:
        capture_daily_snapshot(db)
        logger.info("Daily intelligence snapshot captured")
    except Exception as e:
        logger.exception("Daily snapshot failed: %s", e)
    finally:
        db.close()


async def _daily_sheet_sync():
    from database import SessionLocal
    from sheets_tour_sync import merge_all_sheets_to_db

    db = SessionLocal()
    try:
        result = merge_all_sheets_to_db(db)
        logger.info("Daily sheet sync: updated=%s inserted=%s", result.get("total_updated"), result.get("total_inserted"))
    except Exception as e:
        logger.exception("Daily sheet sync failed: %s", e)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _auto_scrape,
        CronTrigger(hour=_schedule_hour, minute=_schedule_minute),
        id="daily_vietravel",
        args=["vietravel"],
        replace_existing=True,
    )
    _scheduler.add_job(
        _auto_scrape,
        CronTrigger(hour=_schedule_hour, minute=_schedule_minute + 20),
        id="daily_findtourgo",
        args=["findtourgo"],
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_snapshot,
        CronTrigger(hour=8, minute=30),
        id="daily_intel_snapshot",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_sheet_sync,
        CronTrigger(hour=9, minute=0),
        id="daily_sheet_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler started: Vietravel at %02d:%02d, FindTourGo at %02d:%02d daily",
        _schedule_hour,
        _schedule_minute,
        _schedule_hour,
        _schedule_minute + 20,
    )


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
