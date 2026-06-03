"""Phát hiện job scraper treo (thread chết sau deploy / lỗi không bắt được)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import ScrapeJob

logger = logging.getLogger(__name__)

# Job đang quét thật (có heartbeat gần đây) — cho phép chạy lâu
_STALE_HOURS: dict[str, float] = {
    "vietravel": 4.0,
    "findtourgo": 3.0,
}
_DEFAULT_STALE_HOURS = 2.0

# 0% progress lâu = thread không chạy / chết ngay sau khi tạo job
_ZERO_PROGRESS_STALE_MIN = 45


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
    limit_h = _STALE_HOURS.get(job.scraper_name, _DEFAULT_STALE_HOURS)
    if job.status == "pending":
        limit_h = min(limit_h, 0.5)

    if (now - hb) >= timedelta(hours=limit_h):
        return "Job treo — server restart hoặc scraper dừng giữa chừng"

    return None


def reconcile_stale_scrape_jobs(db: Session, *, now: datetime | None = None) -> list[int]:
    """
    Đánh dấu failed các job pending/running không còn thread thật.
    Trả về danh sách job id đã sửa.
    """
    now = now or datetime.utcnow()
    fixed: list[int] = []

    rows = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.status.in_(("pending", "running")))
        .all()
    )
    for job in rows:
        reason = _is_stale_job(job, now)
        if not reason:
            continue
        was = job.status
        _mark_stale(job, now, reason=reason)
        fixed.append(job.id)
        logger.warning(
            "Reconciled stale scrape job id=%s scraper=%s was=%s reason=%s",
            job.id,
            job.scraper_name,
            was,
            reason,
        )

    if fixed:
        db.commit()
    return fixed
