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


def remove_from_unmatched_cache(db, scope_field: str, value: str) -> bool:
    """Incremental update sau khi GÁN alias: xóa đúng dòng ``value`` khỏi cache
    unmatched thay vì vứt cả cache → panel «Chưa khớp» GET sau = instant (không
    full scan) và đã mất dòng vừa gán.

    Vì cache key chứa fingerprint (tours, rules) và sau khi insert rule + targeted
    apply CẢ HAI fingerprint đều đổi, entry cũ sẽ thành mồ côi (miss vĩnh viễn).
    → Mutate data in-place rồi REKEY entry sang fingerprint hiện tại (cần ``db``
    để đọc fingerprint — gọi SAU khi đã commit rule + targeted apply).

    scope_field: key trong dict unmatched — "cong_ty" | "diem_kh" | "thoi_gian" | "lich_kh".
    Trả True nếu có cache được giữ lại (rekey thành công); False = cache trống
    (GET sau recompute cold như cũ). Lỗi bất kỳ → fallback invalidate toàn bộ (an toàn).
    """
    val = (value or "").strip().lower()
    if not val or not scope_field:
        invalidate_unmatched_cache()
        return False
    try:
        tour_fp = _tour_fingerprint(db)
        rules_fp = _rules_fingerprint(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("remove_from_unmatched_cache: fingerprint failed (%s) → invalidate", e)
        invalidate_unmatched_cache()
        return False

    kept = False
    with _lock:
        if not _unmatched_cache:
            return False
        # Giữ entry MỚI NHẤT per scope (bỏ key fingerprint cũ), rekey sang fp hiện tại.
        latest: dict[str, tuple[float, Any]] = {}
        for (scope, _tfp, _rfp), (ts, data) in _unmatched_cache.items():
            cur = latest.get(scope)
            if cur is None or ts > cur[0]:
                latest[scope] = (ts, data)
        _unmatched_cache.clear()
        for scope, (ts, data) in latest.items():
            if isinstance(data, dict):
                rows = data.get(scope_field)
                if isinstance(rows, list):
                    data[scope_field] = [
                        r
                        for r in rows
                        if not (
                            isinstance(r, dict)
                            and str(r.get("value", "")).strip().lower() == val
                        )
                    ]
            # Giữ nguyên ts gốc → TTL 600s vẫn áp dụng từ lần compute thật.
            _unmatched_cache[(scope, tour_fp, rules_fp)] = (ts, data)
            kept = True
    return kept


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
        DateFormatRule,
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
    # DateFormatRule (pattern-based parser cho lich_kh) — thay đổi sẽ ảnh hưởng
    # parse_departure_dates → tần suất KH; invalidate cache khi rule mutation.
    df = db.query(func.count(DateFormatRule.id), func.max(DateFormatRule.updated_at)).one()
    kv = db.get(AppKv, MARKET_ORDER_KV_KEY)
    kv_ts = kv.updated_at.isoformat() if kv and kv.updated_at else None
    return (
        int(mk[0] or 0), mk[1].isoformat() if mk[1] else None,
        int(rt[0] or 0), rt[1].isoformat() if rt[1] else None,
        int(co[0] or 0), co[1].isoformat() if co[1] else None,
        int(dp[0] or 0), dp[1].isoformat() if dp[1] else None,
        int(du[0] or 0), du[1].isoformat() if du[1] else None,
        int(sc[0] or 0), sc[1].isoformat() if sc[1] else None,
        int(df[0] or 0), df[1].isoformat() if df[1] else None,
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
