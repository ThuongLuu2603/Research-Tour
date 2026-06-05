from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

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


def _load_schedule_from_db() -> None:
    global _schedule_hour, _schedule_minute
    try:
        from config import settings
        from database import SessionLocal
        from scheduler_store import load_saved_schedule

        db = SessionLocal()
        try:
            saved = load_saved_schedule(db)
            if saved:
                _schedule_hour, _schedule_minute = saved
            else:
                _schedule_hour = settings.scraper_schedule_hour
                _schedule_minute = settings.scraper_schedule_minute
        finally:
            db.close()
    except Exception as e:
        logger.warning("Could not load scraper schedule from DB: %s", e)


def _job_plan(hour: int | None = None, minute: int | None = None) -> list[tuple[str, str, int, int]]:
    h = _schedule_hour if hour is None else hour
    m = _schedule_minute if minute is None else minute
    ftg_h, ftg_m = _add_minutes(h, m, 20)
    main_h, main_m = _add_minutes(h, m, 50)
    return [
        ("daily_vietravel", "Scrape Vietravel", h, m),
        ("daily_findtourgo", "Scrape FindTourGo → Sheet", ftg_h, ftg_m),
        ("daily_main_sheet_sync", "Sync Main → DB", main_h, main_m),
        ("daily_intel_snapshot", "Snapshot", 8, 30),
        ("daily_sheet_sync", "Sync Main + Vietravel Sheet → DB", 9, 0),
    ]


def get_schedule_config() -> dict:
    from database import SessionLocal
    from scheduler_store import load_last_runs

    jobs = [
        {"id": job_id, "label": label, "time_vn": f"{hh:02d}:{mm:02d}"}
        for job_id, label, hh, mm in _job_plan()
    ]
    last_runs: dict[str, str] = {}
    try:
        db = SessionLocal()
        try:
            last_runs = load_last_runs(db)
        finally:
            db.close()
    except Exception:
        pass
    for job in jobs:
        job["last_run_at"] = last_runs.get(job["id"])
    return {
        "hour": _schedule_hour,
        "minute": _schedule_minute,
        "timezone": VN_TZ_NAME,
        "timezone_label": "Giờ Việt Nam (UTC+7)",
        "enabled": _scheduler is not None,
        "jobs": jobs,
    }


def update_schedule_config(hour: int, minute: int, db=None) -> None:
    global _schedule_hour, _schedule_minute
    _schedule_hour = hour
    _schedule_minute = minute
    ftg_h, ftg_m = _add_minutes(hour, minute, 20)

    own_session = db is None
    if own_session:
        from database import SessionLocal

        db = SessionLocal()
    try:
        from scheduler_store import save_schedule

        save_schedule(db, hour, minute)
    finally:
        if own_session:
            db.close()

    if _scheduler:
        _scheduler.reschedule_job("daily_vietravel", trigger=_vn_cron(hour, minute))
        _scheduler.reschedule_job("daily_findtourgo", trigger=_vn_cron(ftg_h, ftg_m))
        main_h, main_m = _add_minutes(hour, minute, 50)
        _scheduler.reschedule_job("daily_main_sheet_sync", trigger=_vn_cron(main_h, main_m))
    logger.info(
        "Schedule updated (VN): Vietravel %02d:%02d, FindTourGo %02d:%02d, Main sync %02d:%02d",
        hour,
        minute,
        ftg_h,
        ftg_m,
        *_add_minutes(hour, minute, 50),
    )


def _vn_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(VN_TZ)


def _is_due(now_vn: datetime, hour: int, minute: int) -> bool:
    scheduled = now_vn.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now_vn >= scheduled


def _already_ran_today(last_runs: dict[str, str], job_id: str, now_vn: datetime) -> bool:
    raw = last_runs.get(job_id)
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(VN_TZ).date() == now_vn.date()
    except ValueError:
        return False


def _queue_scrape(scraper_name: str, triggered_by: str = "scheduler") -> int | None:
    from api.scraper import _run_job
    from database import SessionLocal
    from models import ScrapeJob
    from scrape_job_utils import reconcile_stale_scrape_jobs

    db = SessionLocal()
    try:
        reconcile_stale_scrape_jobs(db)
        running = (
            db.query(ScrapeJob)
            .filter(ScrapeJob.scraper_name == scraper_name, ScrapeJob.status == "running")
            .first()
        )
        if running:
            logger.warning(
                "Skip scheduled %s: job %s still running since %s",
                scraper_name,
                running.id,
                running.started_at,
            )
            return None

        job = ScrapeJob(
            scraper_name=scraper_name,
            status="pending",
            triggered_by=triggered_by,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    threading.Thread(target=_run_job, args=(job_id, scraper_name), daemon=True).start()
    logger.info("Scrape triggered (%s): %s job_id=%d", triggered_by, scraper_name, job_id)
    return job_id


def _run_main_sheet_sync() -> None:
    from database import SessionLocal
    from sheets_tour_sync import merge_sheet_source_to_db
    from db_retry import run_with_retry

    db = SessionLocal()
    try:
        result = run_with_retry(
            lambda: merge_sheet_source_to_db(db, "Main", mirror_delete=True), db=db, label="sched-main"
        )
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


def _run_daily_snapshot() -> None:
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


def _run_daily_sheet_sync() -> None:
    from database import SessionLocal
    from sheets_tour_sync import merge_all_sheets_to_db
    from db_retry import run_with_retry

    db = SessionLocal()
    try:
        result = run_with_retry(lambda: merge_all_sheets_to_db(db), db=db, label="sched-daily-sync")
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


def _mark_job(job_id: str) -> None:
    from database import SessionLocal
    from scheduler_store import mark_job_run

    db = SessionLocal()
    try:
        mark_job_run(db, job_id)
    finally:
        db.close()


def _execute_job(job_id: str, triggered_by: str) -> None:
    if job_id == "daily_main_sheet_sync":
        threading.Thread(target=_run_main_sheet_sync, daemon=True, name=job_id).start()
    elif job_id == "daily_vietravel":
        _queue_scrape("vietravel", triggered_by=triggered_by)
    elif job_id == "daily_findtourgo":
        _queue_scrape("findtourgo", triggered_by=triggered_by)
    elif job_id == "daily_intel_snapshot":
        threading.Thread(target=_run_daily_snapshot, daemon=True, name=job_id).start()
    elif job_id == "daily_sheet_sync":
        threading.Thread(target=_run_daily_sheet_sync, daemon=True, name=job_id).start()


def run_due_scheduled_jobs(*, triggered_by: str = "cron") -> dict:
    """Chạy các tác vụ đã đến giờ (VN) và chưa chạy hôm nay — dùng cho /api/cron/tick."""
    from database import SessionLocal
    from scheduler_store import load_last_runs, mark_job_run

    now_vn = _vn_now()
    db = SessionLocal()
    try:
        last_runs = load_last_runs(db)
        ran: list[str] = []
        skipped: list[str] = []
        for job_id, _label, hh, mm in _job_plan():
            if not _is_due(now_vn, hh, mm):
                continue
            if _already_ran_today(last_runs, job_id, now_vn):
                skipped.append(job_id)
                continue
            _execute_job(job_id, triggered_by=triggered_by)
            mark_job_run(db, job_id)
            ran.append(job_id)
        return {
            "checked_at_vn": now_vn.isoformat(),
            "ran": ran,
            "skipped_already_ran": skipped,
        }
    finally:
        db.close()


async def _auto_scrape(scraper_name: str):
    job_id = "daily_vietravel" if scraper_name == "vietravel" else "daily_findtourgo"
    if _queue_scrape(scraper_name, triggered_by="scheduler") is not None:
        _mark_job(job_id)


async def _daily_snapshot():
    _run_daily_snapshot()
    _mark_job("daily_intel_snapshot")


async def _sync_main_sheet():
    _run_main_sheet_sync()
    _mark_job("daily_main_sheet_sync")


async def _daily_sheet_sync():
    _run_daily_sheet_sync()
    _mark_job("daily_sheet_sync")


def start_scheduler():
    global _scheduler
    _load_schedule_from_db()
    _scheduler = AsyncIOScheduler(timezone=VN_TZ)
    ftg_h, ftg_m = _add_minutes(_schedule_hour, _schedule_minute, 20)
    main_h, main_m = _add_minutes(_schedule_hour, _schedule_minute, 50)

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
        _vn_cron(main_h, main_m),
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
    _scheduler.add_job(
        run_due_scheduled_jobs,
        IntervalTrigger(minutes=15),
        id="scheduler_catchup_tick",
        kwargs={"triggered_by": "scheduler_tick"},
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler (VN %s): Vietravel %02d:%02d, FindTourGo %02d:%02d, Main sync %02d:%02d, snapshot 08:30, all sheets 09:00 + catchup/15m",
        VN_TZ_NAME,
        _schedule_hour,
        _schedule_minute,
        ftg_h,
        ftg_m,
        main_h,
        main_m,
    )


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
