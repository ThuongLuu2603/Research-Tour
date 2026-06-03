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


def get_apply_status() -> dict:
    db = SessionLocal()
    try:
        row = db.get(AppKv, APPLY_STATUS_KEY)
        if not row or not row.value_json:
            return {"running": False}
        return json.loads(row.value_json)
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
    from models import AppKv, MarketKeywordRule, RouteKeywordRule

    mk = db.query(func.count(MarketKeywordRule.id), func.max(MarketKeywordRule.updated_at)).one()
    rt = db.query(func.count(RouteKeywordRule.id), func.max(RouteKeywordRule.updated_at)).one()
    kv = db.get(AppKv, MARKET_ORDER_KV_KEY)
    kv_ts = kv.updated_at.isoformat() if kv and kv.updated_at else None
    return (
        int(mk[0] or 0),
        mk[1].isoformat() if mk[1] else None,
        int(rt[0] or 0),
        rt[1].isoformat() if rt[1] else None,
        kv_ts,
    )


def get_unmatched_cached(db, scope: str, loader: Callable[[], dict]) -> dict:
    fp = _tour_fingerprint(db)
    rules_fp = _rules_fingerprint(db)
    key = (scope, fp, rules_fp)
    now = time.time()
    with _lock:
        hit = _unmatched_cache.get(key)
        if hit and now - hit[0] < 180:
            return hit[1]
    data = loader()
    with _lock:
        _unmatched_cache[key] = (time.time(), data)
    return data
