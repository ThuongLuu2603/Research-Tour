"""Lưu cấu hình lịch scraper + lần chạy gần nhất (Supabase app_kv)."""
from __future__ import annotations

import json
from datetime import datetime

from models import AppKv

SCHEDULE_KV_KEY = "scraper_schedule"
LAST_RUN_KV_KEY = "scraper_last_run"


def load_saved_schedule(db) -> tuple[int, int] | None:
    row = db.get(AppKv, SCHEDULE_KV_KEY)
    if not row or not row.value_json:
        return None
    try:
        data = json.loads(row.value_json)
        return int(data["hour"]), int(data["minute"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def save_schedule(db, hour: int, minute: int) -> None:
    payload = json.dumps({"hour": hour, "minute": minute}, ensure_ascii=False)

    def _do():
        row = db.get(AppKv, SCHEDULE_KV_KEY)
        if not row:
            db.add(AppKv(key=SCHEDULE_KV_KEY, value_json=payload))
        else:
            row.value_json = payload
        db.commit()

    try:
        from db_retry import run_with_retry
        run_with_retry(_do, db=db, label="save-schedule")
    except Exception:
        _do()  # db_retry không khả dụng → thử trực tiếp


def load_last_runs(db) -> dict[str, str]:
    row = db.get(AppKv, LAST_RUN_KV_KEY)
    if not row or not row.value_json:
        return {}
    try:
        data = json.loads(row.value_json)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def mark_job_run(db, job_id: str, when: datetime | None = None) -> None:
    when = when or datetime.utcnow()
    runs = load_last_runs(db)
    runs[job_id] = when.isoformat()
    row = db.get(AppKv, LAST_RUN_KV_KEY)
    payload = json.dumps(runs, ensure_ascii=False)
    if not row:
        row = AppKv(key=LAST_RUN_KV_KEY, value_json=payload)
        db.add(row)
    else:
        row.value_json = payload
    db.commit()
