"""Cron tick — đánh thức server Render free và chạy scraper đúng giờ VN."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter(prefix="/api/cron", tags=["cron"])


def _verify_cron_secret(authorization: str | None = Header(default=None)) -> None:
    from config import settings

    expected = (os.getenv("CRON_SECRET") or settings.cron_secret or settings.secret_key).strip()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Thiếu Authorization Bearer")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=403, detail="Cron secret không hợp lệ")


@router.post("/tick")
def cron_tick(_: None = Depends(_verify_cron_secret)):
    """
    Gọi mỗi 10–15 phút từ GitHub Actions / cron-job.org.
    Chạy các tác vụ scraper/sync đã đến giờ (VN) và chưa chạy trong ngày.
    """
    from scheduler import run_due_scheduled_jobs

    return run_due_scheduled_jobs(triggered_by="cron")
