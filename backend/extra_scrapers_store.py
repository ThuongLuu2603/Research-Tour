"""Lưu danh sách extra scraper ĐANG BẬT auto (AppKv JSON list).

Key `extra_scrapers_enabled` → JSON list các key đang bật auto trong chuỗi hàng ngày.
"""
from __future__ import annotations

import json
import logging

from database import SessionLocal
from models import AppKv

logger = logging.getLogger(__name__)

ENABLED_KEY = "extra_scrapers_enabled"


def get_enabled_keys() -> list[str]:
    """Danh sách key extra scraper đang bật auto. Lỗi/đọc hỏng → []."""
    db = SessionLocal()
    try:
        row = db.get(AppKv, ENABLED_KEY)
        if not row or not row.value_json:
            return []
        data = json.loads(row.value_json)
        if isinstance(data, list):
            return [str(k) for k in data if str(k).strip()]
        return []
    except Exception as e:  # noqa: BLE001
        logger.warning("get_enabled_keys failed: %s", e)
        return []
    finally:
        db.close()


def set_enabled(key: str, enabled: bool) -> list[str]:
    """Bật/tắt 1 key trong list auto. Trả về list sau khi cập nhật."""
    key = (key or "").strip()
    if not key:
        raise ValueError("key không được rỗng")

    db = SessionLocal()
    try:
        row = db.get(AppKv, ENABLED_KEY)
        if not row:
            row = AppKv(key=ENABLED_KEY, value_json="[]")
            db.add(row)
        try:
            current = json.loads(row.value_json) if row.value_json else []
            if not isinstance(current, list):
                current = []
        except Exception:  # noqa: BLE001
            current = []
        current = [str(k) for k in current if str(k).strip()]

        if enabled and key not in current:
            current.append(key)
        elif not enabled and key in current:
            current = [k for k in current if k != key]

        row.value_json = json.dumps(current, ensure_ascii=False)
        db.commit()
        return current
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.warning("set_enabled failed: %s", e)
        raise
    finally:
        db.close()
