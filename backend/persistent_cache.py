"""Persistent disk cache cho compute results.

Mỗi lần endpoint nặng (home_brief, compare/summary, report/html) compute live
thành công → save kết quả ra disk. Backend restart → load lại tức thì (< 100ms)
thay vì rebuild 40s từ DB.

Strategy:
  1. Live compute → cache trong memory + Redis (5min TTL) + DISK (24h TTL)
  2. Restart backend → memory + Redis trống → load từ DISK (instant)
  3. Background prewarm chạy → live compute mới → overwrite disk

User experience: lần đầu sau restart = data từ live compute lần trước (đại đa số
trường hợp < 24h). Sau prewarm xong (background) → live data mới được lưu disk
cho lần restart kế tiếp.

Files saved at /var/cache/ota/ (fallback /tmp/ota_cache/ nếu không có quyền).
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache dir — ưu tiên /var/cache/ota (persistent), fallback /tmp
_DEFAULT_DIR = "/var/cache/ota"
_FALLBACK_DIR = "/tmp/ota_cache"


def _get_cache_dir() -> Path:
    """Resolve cache dir. Tự fallback nếu không write được."""
    primary = Path(os.getenv("OTA_CACHE_DIR", _DEFAULT_DIR))
    for candidate in (primary, Path(_FALLBACK_DIR)):
        try:
            candidate.mkdir(parents=True, exist_ok=True, mode=0o755)
            # Test write
            test_file = candidate / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
            return candidate
        except (PermissionError, OSError):
            continue
    # Last resort: working dir
    logger.warning("Cache dir fallback to working dir — không persistent!")
    return Path(".")


CACHE_DIR = _get_cache_dir()
logger.info("Persistent cache dir: %s", CACHE_DIR)


def save_json(namespace: str, data, ttl_hours: int = 24) -> bool:
    """Save dict/list ra disk dạng JSON. Trả True nếu thành công."""
    try:
        path = CACHE_DIR / f"{namespace}.json"
        tmp = path.with_suffix(".tmp")
        wrapped = {"saved_at": time.time(), "ttl_hours": ttl_hours, "data": data}
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(wrapped, f, default=str, ensure_ascii=False)
        tmp.replace(path)  # atomic
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("Persistent save %s failed: %s", namespace, e)
        return False


def load_json(namespace: str, max_age_hours: int | None = None) -> dict | list | None:
    """Load từ disk. None nếu file không có hoặc stale.

    max_age_hours: override ttl_hours đã lưu. None = dùng ttl_hours từ file.
    """
    try:
        path = CACHE_DIR / f"{namespace}.json"
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            wrapped = json.load(f)
        saved_at = wrapped.get("saved_at", 0)
        ttl = max_age_hours if max_age_hours is not None else wrapped.get("ttl_hours", 24)
        age_h = (time.time() - saved_at) / 3600
        if age_h > ttl:
            logger.debug("Persistent %s stale (%.1fh > %dh TTL)", namespace, age_h, ttl)
            return None
        return wrapped.get("data")
    except Exception as e:  # noqa: BLE001
        logger.debug("Persistent load %s failed: %s", namespace, e)
        return None


def save_text(namespace: str, content: str, ttl_hours: int = 24) -> bool:
    """Save HTML/text ra disk. Trả True nếu thành công."""
    try:
        path = CACHE_DIR / f"{namespace}.html"
        meta_path = CACHE_DIR / f"{namespace}.html.meta"
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        tmp.replace(path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "ttl_hours": ttl_hours}, f)
        return True
    except Exception as e:  # noqa: BLE001
        logger.debug("Persistent save_text %s failed: %s", namespace, e)
        return False


def load_text(namespace: str, max_age_hours: int | None = None) -> str | None:
    """Load HTML/text từ disk. None nếu không có hoặc stale."""
    try:
        path = CACHE_DIR / f"{namespace}.html"
        meta_path = CACHE_DIR / f"{namespace}.html.meta"
        if not path.exists() or not meta_path.exists():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        saved_at = meta.get("saved_at", 0)
        ttl = max_age_hours if max_age_hours is not None else meta.get("ttl_hours", 24)
        age_h = (time.time() - saved_at) / 3600
        if age_h > ttl:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        logger.debug("Persistent load_text %s failed: %s", namespace, e)
        return None


def stats() -> dict:
    """Trả info về cache dir + size."""
    try:
        total_files = 0
        total_size = 0
        if CACHE_DIR.exists():
            for p in CACHE_DIR.iterdir():
                if p.is_file():
                    total_files += 1
                    total_size += p.stat().st_size
        return {
            "cache_dir": str(CACHE_DIR),
            "files": total_files,
            "total_bytes": total_size,
        }
    except Exception as e:  # noqa: BLE001
        return {"cache_dir": str(CACHE_DIR), "error": str(e)}
