"""Phát hiện job scraper treo (thread chết sau deploy / lỗi không bắt được)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import ScrapeJob

logger = logging.getLogger(__name__)

# Vietravel: quét + merge DB + ghi Sheet — thường < 90 phút
_STALE_HOURS: dict[str, float] = {
    "vietravel": 3.0,
    "findtourgo": 2.0,
}
_DEFAULT_STALE_HOURS = 2.0


def reconcile_stale_scrape_jobs(db: Session, *, now: datetime | None = None) -> list[int]:
    """
    Đánh dấu failed các job pending/running quá lâu (không còn thread thật sự chạy).
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
        ref = job.started_at or now
        limit_h = _STALE_HOURS.get(job.scraper_name, _DEFAULT_STALE_HOURS)
        if job.status == "pending" and not job.started_at:
            limit_h = min(limit_h, 0.5)
        if now - ref < timedelta(hours=limit_h):
            continue
        age_h = (now - ref).total_seconds() / 3600
        was = job.status
        job.status = "failed"
        job.finished_at = now
        job.progress_pct = job.progress_pct or 0
        prev = (job.message or "").strip()
        note = (
            f"Job treo ~{age_h:.1f}h — có thể server restart hoặc scraper dừng giữa chừng. "
            f"Bấm «Chạy ngay» để chạy lại."
        )
        job.message = f"{prev} | {note}"[:512] if prev else note[:512]
        fixed.append(job.id)
        logger.warning(
            "Reconciled stale scrape job id=%s scraper=%s status_was=%s age_h=%.1f",
            job.id,
            job.scraper_name,
            was,
            age_h,
        )

    if fixed:
        db.commit()
    return fixed
