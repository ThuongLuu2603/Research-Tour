"""Compare rule config — admin-configurable VTR tier ↔ Market phân khúc filter.

Trước đây hardcoded trong compare_engine:
    VTR_PRICE_TIERS = {"tiết kiệm", "giá tốt"}
    MARKET_PRICE_PHAN_KHUC = {"premium"}

Giờ lưu trong AppKv (key="compare_segment_rule") để admin sửa qua UI mà không cần deploy.

Schema JSON value:
{
  "vtr_tiers": ["Tiết kiệm", "Giá Tốt"],
  "market_phan_khuc": ["Premium"],
  "updated_at": "2026-06-09T10:00:00",
  "updated_by": "admin"
}

Cache 5 phút (in-memory) để compare_engine không hit DB mỗi lần segment compare.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

APP_KV_KEY = "compare_segment_rule"

# Default tương thích logic cũ — sẽ dùng khi AppKv trống.
DEFAULT_VTR_TIERS = ["Tiết kiệm", "Giá Tốt"]
DEFAULT_MARKET_PHAN_KHUC = ["Premium"]

# Tất cả option có sẵn — UI dropdown / multiselect dùng. Phải khớp với:
#   - vietravel_scraper._TOURLINE_BY_ID (Dòng tour Vietravel)
#   - pricing_segments label (Standard/Premium/Luxury)
AVAILABLE_VTR_TIERS = ["Tour ESG & LEI", "Tiêu chuẩn", "Tiết kiệm", "Giá Tốt", "Cao cấp"]
AVAILABLE_MARKET_PHAN_KHUC = ["Standard", "Premium", "Luxury"]

_CACHE_TTL_SEC = 300  # 5 phút
_cache: dict[str, Any] = {"data": None, "expires": 0}
_cache_lock = threading.Lock()


def _default_config() -> dict[str, Any]:
    return {
        "vtr_tiers": list(DEFAULT_VTR_TIERS),
        "market_phan_khuc": list(DEFAULT_MARKET_PHAN_KHUC),
        "updated_at": None,
        "updated_by": None,
        "is_default": True,
    }


def _load_from_db() -> dict[str, Any]:
    """Đọc rule từ AppKv. Fallback default nếu chưa có hoặc lỗi parse."""
    try:
        from database import SessionLocal
        from models import AppKv

        db = SessionLocal()
        try:
            row = db.query(AppKv).filter(AppKv.key == APP_KV_KEY).first()
            if not row or not row.value_json:
                return _default_config()
            data = json.loads(row.value_json)
            # Validate shape
            tiers = data.get("vtr_tiers") or []
            phk = data.get("market_phan_khuc") or []
            if not isinstance(tiers, list) or not isinstance(phk, list):
                logger.warning("compare_segment_rule shape invalid, fallback default: %r", data)
                return _default_config()
            return {
                "vtr_tiers": [str(t) for t in tiers],
                "market_phan_khuc": [str(p) for p in phk],
                "updated_at": data.get("updated_at"),
                "updated_by": data.get("updated_by"),
                "is_default": False,
            }
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("Load compare_segment_rule failed, fallback default: %s", e)
        return _default_config()


def get_compare_rule_config() -> dict[str, Any]:
    """Trả rule active. Cached 5 phút."""
    now = time.time()
    with _cache_lock:
        if _cache["data"] is not None and now < _cache["expires"]:
            return _cache["data"]
        data = _load_from_db()
        _cache["data"] = data
        _cache["expires"] = now + _CACHE_TTL_SEC
        return data


def invalidate_cache() -> None:
    """Gọi sau khi admin update rule — buộc reload lần kế tiếp."""
    with _cache_lock:
        _cache["data"] = None
        _cache["expires"] = 0


def save_compare_rule(
    vtr_tiers: list[str],
    market_phan_khuc: list[str],
    updated_by: str = "admin",
) -> dict[str, Any]:
    """Validate + ghi rule mới vào AppKv. Trả config mới sau invalidate cache."""
    from datetime import datetime

    from database import SessionLocal
    from models import AppKv

    # Validate
    tiers_clean = [str(t).strip() for t in vtr_tiers if str(t).strip()]
    phk_clean = [str(p).strip() for p in market_phan_khuc if str(p).strip()]
    if not tiers_clean:
        raise ValueError("Phải chọn ít nhất 1 Dòng tour Vietravel")
    if not phk_clean:
        raise ValueError("Phải chọn ít nhất 1 Phân khúc thị trường")
    # Cảnh báo (không block) tier/phk không trong danh sách quen thuộc — vẫn lưu để
    # support custom future values.
    for t in tiers_clean:
        if t not in AVAILABLE_VTR_TIERS:
            logger.warning("compare rule vtr_tier=%r không có trong AVAILABLE_VTR_TIERS — vẫn lưu", t)
    for p in phk_clean:
        if p not in AVAILABLE_MARKET_PHAN_KHUC:
            logger.warning("compare rule market_phk=%r không có trong AVAILABLE_MARKET_PHAN_KHUC — vẫn lưu", p)

    value = {
        "vtr_tiers": tiers_clean,
        "market_phan_khuc": phk_clean,
        "updated_at": datetime.utcnow().isoformat(),
        "updated_by": updated_by,
    }
    db = SessionLocal()
    try:
        row = db.query(AppKv).filter(AppKv.key == APP_KV_KEY).first()
        if row:
            row.value_json = json.dumps(value, ensure_ascii=False)
            row.updated_at = datetime.utcnow()
        else:
            row = AppKv(key=APP_KV_KEY, value_json=json.dumps(value, ensure_ascii=False))
            db.add(row)
        db.commit()
    finally:
        db.close()

    invalidate_cache()
    return get_compare_rule_config()


def get_vtr_tier_set() -> set[str]:
    """Lower-cased set cho lookup trong compare_engine — KHÔNG strip whitespace inner."""
    cfg = get_compare_rule_config()
    return {t.strip().lower() for t in cfg["vtr_tiers"] if t.strip()}


def get_market_phan_khuc_set() -> set[str]:
    cfg = get_compare_rule_config()
    return {p.strip().lower() for p in cfg["market_phan_khuc"] if p.strip()}
