from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
VN_TZ_NAME = "Asia/Ho_Chi_Minh"

_scheduler: AsyncIOScheduler | None = None
_schedule_hour = 7
_schedule_minute = 0

def _vn_cron(hour: int, minute: int) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=VN_TZ)


def _add_minutes(hour: int, minute: int, offset: int) -> tuple[int, int]:
    total = hour * 60 + minute + offset
    return (total // 60) % 24, total % 60


def get_schedule_config() -> dict:
    ftg_h, ftg_m = _add_minutes(_schedule_hour, _schedule_minute, 20)
    jobs = [
        {"id": "daily_main_sheet_sync", "label": "Sync Main → DB", "time_vn": "06:30"},
        {"id": "daily_vietravel", "label": "Scrape Vietravel", "time_vn": f"{_schedule_hour:02d}:{_schedule_minute:02d}"},
        {"id": "daily_findtourgo", "label": "Scrape FindTourGo", "time_vn": f"{ftg_h:02d}:{ftg_m:02d}"},
        {"id": "daily_intel_snapshot", "label": "Snapshot", "time_vn": "08:30"},
        {"id": "daily_sheet_sync", "label": "Sync tất cả tab", "time_vn": "09:00"},
    ]
    return {
        "hour": _schedule_hour,
        "minute": _schedule_minute,
        "timezone": VN_TZ_NAME,
        "timezone_label": "Giờ Việt Nam (UTC+7)",
        "enabled": _scheduler is not None,
        "jobs": jobs,
    }


def update_schedule_config(hour: int, minute: int):
    global _schedule_hour, _schedule_minute
    _schedule_hour = hour
    _schedule_minute = minute
    ftg_h, ftg_m = _add_minutes(hour, minute, 20)
    if _scheduler:
        _scheduler.reschedule_job("daily_vietravel", trigger=_vn_cron(hour, minute))
        _scheduler.reschedule_job("daily_findtourgo", trigger=_vn_cron(ftg_h, ftg_m))
    logger.info("Schedule updated (VN): Vietravel %02d:%02d, FindTourGo %02d:%02d", hour, minute, ftg_h, ftg_m)


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


async def _sync_main_sheet():
    """Sheet Main — cập nhật sau Google Apps Script scrape (≈ 00:00–06:00 VN)."""
    from database import SessionLocal
    from sheets_tour_sync import merge_sheet_source_to_db

    db = SessionLocal()
    try:
        result = merge_sheet_source_to_db(db, "Main", mirror_delete=False)
        logger.info(
            "Main sheet sync: inserted=%s updated=%s unchanged=%s",
            result.get("inserted"),
            result.get("updated"),
            result.get("unchanged"),
        )
    except Exception as e:
        logger.exception("Main sheet sync failed: %s", e)
    finally:
        db.close()


async def _daily_sheet_sync():
    from database import SessionLocal
    from sheets_tour_sync import merge_all_sheets_to_db

    db = SessionLocal()
    try:
        result = merge_all_sheets_to_db(db)
        logger.info(
            "Daily sheet sync: updated=%s inserted=%s deleted=%s",
            result.get("total_updated"),
            result.get("total_inserted"),
            result.get("total_deleted"),
        )
    except Exception as e:
        logger.exception("Daily sheet sync failed: %s", e)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    _scheduler = AsyncIOScheduler(timezone=VN_TZ)
    ftg_h, ftg_m = _add_minutes(_schedule_hour, _schedule_minute, 20)

    _scheduler.add_job(
        _auto_scrape,
        _vn_cron(_schedule_hour, _schedule_minute),
        id="daily_vietravel",
        args=["vietravel"],
        replace_existing=True,
    )
    _scheduler.add_job(
        _auto_scrape,
        _vn_cron(ftg_h, ftg_m),
        id="daily_findtourgo",
        args=["findtourgo"],
        replace_existing=True,
    )
    _scheduler.add_job(
        _sync_main_sheet,
        _vn_cron(6, 30),
        id="daily_main_sheet_sync",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_snapshot,
        _vn_cron(8, 30),
        id="daily_intel_snapshot",
        replace_existing=True,
    )
    _scheduler.add_job(
        _daily_sheet_sync,
        _vn_cron(9, 0),
        id="daily_sheet_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler (VN %s): Main 06:30, Vietravel %02d:%02d, FindTourGo %02d:%02d, snapshot 08:30, all sheets 09:00",
        VN_TZ_NAME,
        _schedule_hour,
        _schedule_minute,
        ftg_h,
        ftg_m,
    )


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
