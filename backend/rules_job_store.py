"""Trạng thái job áp dụng quy tắc + cache unmatched — lưu DB (ổn định multi-worker Render)."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

from database import SessionLocal
from models import AppKv

logger = logging.getLogger(__name__)

APPLY_STATUS_KEY = "rules_apply_status"
APPLY_STALE_SECONDS = 45 * 60
APPLY_PROGRESS_STALE_SECONDS = 12 * 60
_lock = threading.Lock()
_unmatched_cache: dict[tuple, tuple[float, Any]] = {}


def set_apply_status(data: dict) -> None:
    db = SessionLocal()
    try:
        row = db.get(AppKv, APPLY_STATUS_KEY)
        if not row:
            row = AppKv(key=APPLY_STATUS_KEY, value_json="{}")
            db.add(row)
        row.value_json = json.dumps(data, ensure_ascii=False)
        db.commit()
    except Exception as e:
        logger.warning("set_apply_status failed: %s", e)
        db.rollback()
    finally:
        db.close()


def _parse_iso_utc(value: str):
    from datetime import datetime, timezone

    t0 = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    return t0


def _normalize_apply_status(raw: dict) -> dict:
    if not raw.get("running"):
        return raw
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        progress_at = raw.get("progress_at")
        if progress_at:
            age = (now - _parse_iso_utc(progress_at)).total_seconds()
            if age > APPLY_PROGRESS_STALE_SECONDS:
                return {
                    "running": False,
                    "stale": True,
                    "message": "Job áp dụng không cập nhật tiến độ >12 phút — có thể treo. Bấm «Áp dụng ngay» để chạy lại.",
                    "last_result": raw.get("last_result"),
                    "progress": raw.get("progress"),
                    "total": raw.get("total"),
                    "last_id": raw.get("last_id"),
                    "params": raw.get("params"),
                }
        started = raw.get("started_at")
        if started:
            age = (now - _parse_iso_utc(started)).total_seconds()
            if age > APPLY_STALE_SECONDS:
                return {
                    "running": False,
                    "stale": True,
                    "message": "Job áp dụng trước đó quá lâu — bạn có thể chạy lại.",
                    "last_result": raw.get("last_result"),
                    "progress": raw.get("progress"),
                    "total": raw.get("total"),
                    "last_id": raw.get("last_id"),
                    "params": raw.get("params"),
                }
    except Exception:
        pass
    return raw


def get_apply_status() -> dict:
    db = SessionLocal()
    try:
        row = db.get(AppKv, APPLY_STATUS_KEY)
        if not row or not row.value_json:
            return {"running": False}
        raw = json.loads(row.value_json)
        norm = _normalize_apply_status(raw)
        if norm.get("stale") and raw.get("running"):
            row.value_json = json.dumps(norm, ensure_ascii=False)
            db.commit()
        return norm
    except Exception:
        return {"running": False}
    finally:
        db.close()


def invalidate_unmatched_cache() -> None:
    with _lock:
        _unmatched_cache.clear()


def _tour_fingerprint(db) -> tuple[int, str | None]:
    from sqlalchemy import func

    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    row = (
        db.query(func.count(Tour.id), func.max(Tour.updated_at))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .one()
    )
    return (int(row[0] or 0), row[1].isoformat() if row[1] else None)


def _rules_fingerprint(db) -> tuple:
    from sqlalchemy import func

    from classify_market_order import MARKET_ORDER_KV_KEY
    from models import (
        AppKv,
        CompanyAliasRule,
        DepartureAliasRule,
        DurationAliasRule,
        MarketKeywordRule,
        RouteKeywordRule,
        ScheduleAliasRule,
    )

    mk = db.query(func.count(MarketKeywordRule.id), func.max(MarketKeywordRule.updated_at)).one()
    rt = db.query(func.count(RouteKeywordRule.id), func.max(RouteKeywordRule.updated_at)).one()
    # BUG fix: cache key trước đây chỉ gồm market+route rules → khi user thêm/xóa
    # company/departure/duration/schedule alias, fingerprint không đổi → cache hit
    # data cũ, các tab tương ứng không thấy alias chưa khớp mới.
    co = db.query(func.count(CompanyAliasRule.id), func.max(CompanyAliasRule.updated_at)).one()
    dp = db.query(func.count(DepartureAliasRule.id), func.max(DepartureAliasRule.updated_at)).one()
    du = db.query(func.count(DurationAliasRule.id), func.max(DurationAliasRule.updated_at)).one()
    sc = db.query(func.count(ScheduleAliasRule.id), func.max(ScheduleAliasRule.updated_at)).one()
    kv = db.get(AppKv, MARKET_ORDER_KV_KEY)
    kv_ts = kv.updated_at.isoformat() if kv and kv.updated_at else None
    return (
        int(mk[0] or 0), mk[1].isoformat() if mk[1] else None,
        int(rt[0] or 0), rt[1].isoformat() if rt[1] else None,
        int(co[0] or 0), co[1].isoformat() if co[1] else None,
        int(dp[0] or 0), dp[1].isoformat() if dp[1] else None,
        int(du[0] or 0), du[1].isoformat() if du[1] else None,
        int(sc[0] or 0), sc[1].isoformat() if sc[1] else None,
        kv_ts,
    )


def get_unmatched_cached(db, scope: str, loader: Callable[[], dict]) -> dict:
    fp = _tour_fingerprint(db)
    rules_fp = _rules_fingerprint(db)
    key = (scope, fp, rules_fp)
    now = time.time()
    with _lock:
        hit = _unmatched_cache.get(key)
        if hit and now - hit[0] < 600:
            return hit[1]
    data = loader()
    with _lock:
        _unmatched_cache[key] = (time.time(), data)
    return data
