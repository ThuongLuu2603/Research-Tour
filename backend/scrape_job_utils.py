"""Phát hiện job scraper treo (thread chết sau deploy / lỗi không bắt được)."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import ScrapeJob

logger = logging.getLogger(__name__)

# Throttle reconcile để giảm tải SELECT IN trên scrape_jobs.
# Endpoint GET /jobs/{id} (UI poll) gọi reconcile mỗi request → CockroachDB cảnh báo
# ReadWithinUncertaintyIntervalError vì heartbeat write đồng thời. Reconcile chỉ cần
# chạy mỗi 30s là đủ phát hiện zombie thread.
_RECONCILE_THROTTLE_SEC = 30.0
_reconcile_last_run = 0.0
_reconcile_lock = threading.Lock()

# Job đang quét thật (có heartbeat gần đây) — cho phép chạy lâu
_STALE_HOURS: dict[str, float] = {
    "vietravel": 4.0,
    "findtourgo": 3.0,
    "sync_main": 2.0,
}
_DEFAULT_STALE_HOURS = 2.0

# 0% progress lâu = thread không chạy / chết ngay sau khi tạo job
_ZERO_PROGRESS_STALE_MIN = 45
# % > 5 (kể cả 100% — đang ở bước hậu-commit) nhưng heartbeat đứng im = thread chết.
# An toàn ở mức thấp vì mọi bước nặng (tsvector/phân khúc) giờ đều đập heartbeat liên tục.
_STUCK_PROGRESS_MIN = 10


def _mark_stale(job: ScrapeJob, now: datetime, *, reason: str) -> None:
    ref = job.heartbeat_at or job.started_at or now
    age_h = max(0.0, (now - ref).total_seconds() / 3600)
    job.status = "failed"
    job.finished_at = now
    job.progress_pct = job.progress_pct or 0
    prev = (job.message or "").strip()
    note = f"{reason} (~{age_h:.1f}h). Bấm «Chạy ngay» để chạy lại."
    job.message = f"{prev} | {note}"[:512] if prev else note[:512]


def _is_stale_job(job: ScrapeJob, now: datetime) -> str | None:
    """Trả về lý do nếu job nên đánh failed; None nếu vẫn hợp lệ."""
    if job.status not in ("pending", "running"):
        return None

    ref = job.heartbeat_at or job.started_at
    if not ref:
        return "Job pending quá lâu"

    age = now - ref
    age_min = age.total_seconds() / 60
    pct = job.progress_pct or 0

    if pct <= 5 and age_min >= _ZERO_PROGRESS_STALE_MIN:
        return "Không có tiến độ — thread scraper có thể đã dừng (deploy/DB)"

    hb = job.heartbeat_at or job.started_at
    if (
        job.status == "running"
        and pct > 5  # kể cả 100% (bước hậu-commit: tsvector/phân khúc/cache)
        and job.heartbeat_at
        and (now - job.heartbeat_at) > timedelta(minutes=_STUCK_PROGRESS_MIN)
    ):
        return "Dừng giữa chừng — không cập nhật tiến độ (thread chết: deploy/restart/DB)"

    limit_h = _STALE_HOURS.get(job.scraper_name, _DEFAULT_STALE_HOURS)
    if job.status == "pending":
        limit_h = min(limit_h, 0.5)

    if (now - hb) >= timedelta(hours=limit_h):
        return "Job treo — server restart hoặc scraper dừng giữa chừng"

    return None


def reconcile_stale_scrape_jobs(
    db: Session,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> list[int]:
    """
    Đánh dấu failed các job pending/running không còn thread thật.
    Trả về danh sách job id đã sửa.

    Throttle: mặc định bỏ qua nếu chạy lần gần nhất < 30s (giảm contention với
    heartbeat write trên scrape_jobs). Truyền force=True khi user bấm nút thủ công.
    """
    global _reconcile_last_run
    if not force:
        with _reconcile_lock:
            now_ts = time.monotonic()
            if now_ts - _reconcile_last_run < _RECONCILE_THROTTLE_SEC:
                return []
            _reconcile_last_run = now_ts

    now = now or datetime.utcnow()
    fixed: list[int] = []

    rows = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.status.in_(("pending", "running")))
        .all()
    )
    released_write_lock = False
    for job in rows:
        reason = _is_stale_job(job, now)
        if not reason:
            continue
        was = job.status
        _mark_stale(job, now, reason=reason)
        fixed.append(job.id)
        # Job ghi DB (sync_main/vietravel) bị reap → thread chết có thể còn giữ khóa ghi tour.
        # Nhả ngay để lần sync sau không bị «Đang có job khác ghi» (lease tự hết hạn sau 5' dù sao).
        if job.scraper_name in ("sync_main", "vietravel"):
            released_write_lock = True
        logger.warning(
            "Reconciled stale scrape job id=%s scraper=%s was=%s reason=%s",
            job.id,
            job.scraper_name,
            was,
            reason,
        )

    if fixed:
        from db_retry import run_with_retry

        def _commit_marks():
            # Re-mark trong phiên mới sau rollback (rollback xoá thay đổi pending) → retry an toàn.
            db.rollback()
            rows_again = (
                db.query(ScrapeJob).filter(ScrapeJob.id.in_(fixed)).all()
            )
            for j in rows_again:
                if j.status in ("pending", "running"):
                    _mark_stale(j, now, reason="Job treo — dọn khi đối soát")
            db.commit()

        try:
            run_with_retry(_commit_marks, db=db, label="reconcile-stale")
        except Exception as e:  # noqa: BLE001
            logger.warning("reconcile commit failed: %s", e)
    if released_write_lock:
        try:
            from db_job_lock import force_release

            force_release()
        except Exception as e:  # noqa: BLE001
            logger.warning("force_release after reconcile failed: %s", e)
    return fixed
