"""Redis cache layer — persistent cache survive backend restart.

Architecture:
  - In-memory cache vẫn là primary (fastest hit path).
  - Mỗi set/get đồng bộ với Redis → khi backend restart, cold-load từ Redis.
  - JSON serialization (NOT pickle) — chỉ cache dữ liệu serialize được (dict, list).
    SQLAlchemy ORM objects KHÔNG cache trực tiếp — phải convert sang dict trước.
  - Fallback gracefully: nếu Redis down, dùng in-memory only (no crash).

Env vars:
  REDIS_URL: redis://127.0.0.1:6379/0 (default empty → Redis disabled)

Usage:
  from redis_cache import redis_get, redis_set, redis_invalidate

  data = redis_get("compare:segments:hash123")
  if data is None:
      data = expensive_compute()
      redis_set("compare:segments:hash123", data, ttl=3600)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

REDIS_URL = (os.getenv("REDIS_URL") or "").strip()
DEFAULT_TTL = int(os.getenv("REDIS_DEFAULT_TTL", "21600"))  # 6h

_client = None
_enabled = False
_lock = threading.Lock()
_last_error_log = 0.0  # rate-limit warning log


def _init() -> None:
    global _client, _enabled
    if not REDIS_URL:
        logger.info("Redis cache: disabled (REDIS_URL not set) — using in-memory fallback only")
        return
    try:
        import redis  # noqa: F401

        _client = redis.Redis.from_url(
            REDIS_URL,
            socket_timeout=2,
            socket_connect_timeout=2,
            health_check_interval=30,
        )
        _client.ping()
        _enabled = True
        info = _client.info(section="server")
        logger.info("Redis cache: connected (version=%s)", info.get("redis_version", "?"))
    except ImportError:
        logger.warning("Redis cache: 'redis' package not installed — pip install redis")
        _client = None
    except Exception as e:  # noqa: BLE001
        logger.warning("Redis cache: connect failed (%s) — fallback in-memory only", e)
        _client = None


_init()


def _warn(msg: str) -> None:
    """Rate-limited warning (max 1/min) — tránh spam log khi Redis down."""
    global _last_error_log
    now = time.time()
    if now - _last_error_log > 60:
        logger.warning(msg)
        _last_error_log = now


def is_enabled() -> bool:
    return _enabled


def redis_get(key: str):
    """Get JSON-decoded value from Redis. None nếu miss/disabled/error."""
    if not _enabled:
        return None
    try:
        val = _client.get(key)
        if val is None:
            return None
        return json.loads(val)
    except Exception as e:  # noqa: BLE001
        _warn(f"Redis GET failed for {key}: {e}")
        return None


def redis_set(key: str, value, ttl: int | None = None) -> bool:
    """Set JSON-encoded value with TTL. Returns True nếu thành công."""
    if not _enabled:
        return False
    try:
        payload = json.dumps(value, default=str, ensure_ascii=False)
        _client.setex(key, ttl or DEFAULT_TTL, payload)
        return True
    except Exception as e:  # noqa: BLE001
        _warn(f"Redis SET failed for {key}: {e}")
        return False


def redis_delete(key: str) -> None:
    if not _enabled:
        return
    try:
        _client.delete(key)
    except Exception as e:  # noqa: BLE001
        _warn(f"Redis DEL failed for {key}: {e}")


def redis_invalidate_pattern(pattern: str) -> int:
    """Xoá tất cả key match pattern (vd 'ota:compare:*'). Trả về số key đã xoá."""
    if not _enabled:
        return 0
    deleted = 0
    try:
        for k in _client.scan_iter(match=pattern, count=1000):
            _client.delete(k)
            deleted += 1
    except Exception as e:  # noqa: BLE001
        _warn(f"Redis SCAN+DEL failed for pattern {pattern}: {e}")
    return deleted


def make_key(namespace: str, **kwargs) -> str:
    """Tạo cache key từ namespace + kwargs. Dùng MD5 của sorted JSON để key deterministic.

    Example: make_key("compare", thi_truong=["VN","TQ"], tuyen_tour="", fp=(8559, "2026-06-09"))
       → "ota:compare:a1b2c3d4e5f6g7h8"
    """
    from hashlib import md5

    data = json.dumps(sorted(kwargs.items()), default=str, ensure_ascii=False)
    digest = md5(data.encode("utf-8")).hexdigest()[:16]
    return f"ota:{namespace}:{digest}"


def cached_json(namespace: str, ttl: int | None = None):
    """Decorator cache function result vào Redis dưới namespace.

    Function args được hash thành cache key. Function result phải JSON-serializable.
    Bỏ qua args không hashable (vd db: Session) — chỉ hash str/int/list/dict.

    Usage:
        @cached_json("festival.dashboard", ttl=3600)
        def get_dashboard_summary(db, region: str = "all"):
            ...
    """
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Hash chỉ những args/kwargs JSON-able. Skip db/session-like (first positional thường là db).
            hashable = {}
            for i, a in enumerate(args[1:], start=1):
                if isinstance(a, (str, int, float, bool, list, tuple, dict, type(None))):
                    hashable[f"a{i}"] = a
            for k, v in kwargs.items():
                if isinstance(v, (str, int, float, bool, list, tuple, dict, type(None))):
                    hashable[k] = v

            key = make_key(namespace, **hashable)
            cached = redis_get(key)
            if cached is not None:
                return cached
            result = fn(*args, **kwargs)
            try:
                # Test serialize trước khi cache (tránh lưu invalid data)
                json.dumps(result, default=str, ensure_ascii=False)
                redis_set(key, result, ttl)
            except (TypeError, ValueError) as e:
                logger.debug("Skip cache (not JSON-serializable): %s %s", namespace, e)
            return result

        return wrapper

    return decorator


def stats() -> dict:
    """Trả Redis stats để monitor: used_memory, hit_rate, keys count."""
    if not _enabled:
        return {"enabled": False}
    try:
        info = _client.info()
        return {
            "enabled": True,
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "keyspace_hits": info.get("keyspace_hits", 0),
            "keyspace_misses": info.get("keyspace_misses", 0),
            "connected_clients": info.get("connected_clients", 0),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0),
        }
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "error": str(e)}
