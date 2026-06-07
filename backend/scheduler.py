from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
VN_TZ_NAME = "Asia/Ho_Chi_Minh"

# BackgroundScheduler thay AsyncIOScheduler — start() được gọi từ
# _bootstrap_database trong daemon thread (không có event loop). AsyncIOScheduler
# yêu cầu asyncio.get_running_loop() → RuntimeError trong thread mới.
# BackgroundScheduler tự tạo thread riêng, hoạt động độc lập với event loop FastAPI.
_scheduler: BackgroundScheduler | None = None
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


def _job_plan(hour: int | None = None, minute: int | None = None) -> list[tuple[str, str, int | None, int | None]]:
    """Mỗi entry = (job_id, label, hour, minute). hour=None nghĩa là bước trong chuỗi —
    chạy tự động ngay sau bước trước (không có giờ cố định)."""
    h = _schedule_hour if hour is None else hour
    m = _schedule_minute if minute is None else minute
    return [
        ("daily_vietravel", "1. Scrape Vietravel", h, m),
        ("daily_findtourgo", "2. Scrape FindTourGo → Sheet", None, None),
        ("daily_main_sheet_sync", "3. Sync Main → DB", None, None),
        ("daily_sheet_sync", "4. Sync All Sheets → DB", None, None),
        ("daily_intel_snapshot", "5. Snapshot BGĐ", None, None),
    ]


def get_schedule_config() -> dict:
    from database import SessionLocal
    from scheduler_store import load_last_runs

    jobs = [
        {
            "id": job_id,
            "label": label,
            "time_vn": (f"{hh:02d}:{mm:02d}" if hh is not None else "→ sau bước trước"),
            "is_trigger": hh is not None,  # FE phân biệt bước có cron riêng vs bước chuỗi
        }
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
        # Chỉ chuỗi có cron trigger; các bước nội bộ tự kích hoạt khi bước trước xong.
        try:
            _scheduler.reschedule_job("daily_chain", trigger=_vn_cron(hour, minute))
        except Exception as e:  # noqa: BLE001
            logger.warning("Reschedule daily_chain failed: %s", e)
    logger.info(
        "Schedule updated (VN): chuỗi khởi động %02d:%02d (Vietravel → FindTourGo → Sync → Snapshot)",
        hour, minute,
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

        from db_retry import run_with_retry

        def _create_job():
            db.rollback()
            j = ScrapeJob(
                scraper_name=scraper_name,
                status="pending",
                triggered_by=triggered_by,
            )
            db.add(j)
            db.commit()
            db.refresh(j)
            return j

        job = run_with_retry(_create_job, db=db, label="sched-job-create")
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
    from db_retry import run_with_retry

    db = SessionLocal()
    try:
        run_with_retry(lambda: capture_daily_snapshot(db), db=db, label="sched-daily-snapshot")
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
            # Bỏ qua bước trong chuỗi (hh=None): chúng tự chạy khi bước trước xong,
            # không có cron riêng. _is_due() ném TypeError nếu pass None.
            if hh is None or mm is None:
                continue
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


def _auto_scrape(scraper_name: str):
    # Sync wrapper — BackgroundScheduler chạy job trong thread, không hỗ trợ async natively.
    # Các hàm bên trong vốn dĩ sync (_queue_scrape, _mark_job), nên `async def` chỉ là wrapper thừa.
    job_id = "daily_vietravel" if scraper_name == "vietravel" else "daily_findtourgo"
    if _queue_scrape(scraper_name, triggered_by="scheduler") is not None:
        _mark_job(job_id)


def _daily_snapshot():
    _run_daily_snapshot()
    _mark_job("daily_intel_snapshot")


def _sync_main_sheet():
    _run_main_sheet_sync()
    _mark_job("daily_main_sheet_sync")


def _daily_sheet_sync():
    _run_daily_sheet_sync()
    _mark_job("daily_sheet_sync")


# Hard cap khi đợi 1 scrape job hoàn tất (giây). Vietravel/FindTourGo thực tế ~5-15ph;
# 90' là ceiling an toàn để chain không treo mãi nếu 1 job kẹt sau khi reaper bỏ sót.
_CHAIN_SCRAPE_WAIT_SEC = 90 * 60
# Khoảng polling DB scrape_jobs để kiểm tra trạng thái (giây).
_CHAIN_POLL_INTERVAL_SEC = 15.0


def _wait_for_scraper_to_finish(scraper_name: str) -> bool:
    """Poll scrape_jobs đến khi không còn job pending/running cho scraper_name.
    Block tối đa _CHAIN_SCRAPE_WAIT_SEC. Trả True nếu xong sạch, False nếu timeout."""
    import time
    from database import SessionLocal
    from models import ScrapeJob

    deadline = time.monotonic() + _CHAIN_SCRAPE_WAIT_SEC
    while time.monotonic() < deadline:
        db = SessionLocal()
        try:
            still_active = (
                db.query(ScrapeJob)
                .filter(
                    ScrapeJob.scraper_name == scraper_name,
                    ScrapeJob.status.in_(("pending", "running")),
                )
                .first()
            )
        finally:
            db.close()
        if not still_active:
            return True
        time.sleep(_CHAIN_POLL_INTERVAL_SEC)
    logger.warning(
        "Chain: đợi %s quá %ss vẫn còn pending/running — chuyển bước kế tiếp",
        scraper_name, _CHAIN_SCRAPE_WAIT_SEC,
    )
    return False


def _run_daily_chain():
    """Chuỗi tự động: Vietravel → FindTourGo → Sync Main → Sync All Sheets → Snapshot.

    Mỗi bước chạy NGAY sau khi bước trước hoàn tất (thay vì chờ cron giờ cố định).
    Bước scrape là async (queue) nên dùng polling DB; bước sync/snapshot chạy inline.
    Một bước fail không chặn các bước sau — log warning và tiếp tục."""
    logger.info("[CHAIN] Bắt đầu chuỗi tự động hàng ngày")

    # 1. Scrape Vietravel
    logger.info("[CHAIN 1/5] Scrape Vietravel")
    try:
        _auto_scrape("vietravel")
        _wait_for_scraper_to_finish("vietravel")
    except Exception as e:  # noqa: BLE001
        logger.exception("[CHAIN 1/5] Vietravel scrape lỗi: %s", e)

    # 2. Scrape FindTourGo → Sheet
    logger.info("[CHAIN 2/5] Scrape FindTourGo")
    try:
        _auto_scrape("findtourgo")
        _wait_for_scraper_to_finish("findtourgo")
    except Exception as e:  # noqa: BLE001
        logger.exception("[CHAIN 2/5] FindTourGo scrape lỗi: %s", e)

    # 3. Sync Main → DB (inline block)
    logger.info("[CHAIN 3/5] Sync Main sheet → DB")
    try:
        _sync_main_sheet()
    except Exception as e:  # noqa: BLE001
        logger.exception("[CHAIN 3/5] Sync Main lỗi: %s", e)

    # 4. Sync All Sheets → DB (Main + Vietravel + FindTourGo tab)
    logger.info("[CHAIN 4/5] Sync tất cả sheet → DB")
    try:
        _daily_sheet_sync()
    except Exception as e:  # noqa: BLE001
        logger.exception("[CHAIN 4/5] Sync all sheets lỗi: %s", e)

    # 5. Snapshot (cuối chuỗi để có data mới nhất)
    logger.info("[CHAIN 5/5] Daily intelligence snapshot")
    try:
        _daily_snapshot()
    except Exception as e:  # noqa: BLE001
        logger.exception("[CHAIN 5/5] Snapshot lỗi: %s", e)

    logger.info("[CHAIN] Hoàn tất chuỗi tự động")


def start_scheduler():
    global _scheduler
    _load_schedule_from_db()
    _scheduler = BackgroundScheduler(timezone=VN_TZ)

    # 1 trigger duy nhất cho cả chuỗi — các bước sau tự kích hoạt khi bước trước xong.
    # max_instances=1 + coalesce=True chặn chồng chuỗi nếu lần chạy trước chưa hết.
    _scheduler.add_job(
        _run_daily_chain,
        _vn_cron(_schedule_hour, _schedule_minute),
        id="daily_chain",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Catch-up tick cho các scheduled job thủ công ngoài chuỗi (workspace, ad-hoc)
    _scheduler.add_job(
        run_due_scheduled_jobs,
        IntervalTrigger(minutes=15),
        id="scheduler_catchup_tick",
        kwargs={"triggered_by": "scheduler_tick"},
        replace_existing=True,
    )

    # Dọn job cũ (5 cron riêng lẻ trước commit chuỗi) — chỉ remove nếu vẫn còn trong store.
    for stale_id in (
        "daily_vietravel",
        "daily_findtourgo",
        "daily_main_sheet_sync",
        "daily_intel_snapshot",
        "daily_sheet_sync",
    ):
        try:
            _scheduler.remove_job(stale_id)
            logger.info("Scheduler: gỡ job cũ %s (đã gộp vào daily_chain)", stale_id)
        except Exception:  # noqa: BLE001
            pass

    _scheduler.start()
    logger.info(
        "Scheduler (VN %s): chuỗi tự động khởi động %02d:%02d → Vietravel → FindTourGo → "
        "Sync Main → Sync All → Snapshot (chain mode, mỗi bước chờ bước trước xong)",
        VN_TZ_NAME, _schedule_hour, _schedule_minute,
    )


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown()
