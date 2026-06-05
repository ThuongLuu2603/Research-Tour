"""Giữ ấm cache So sánh / Market Lab ở nền, có throttle dùng chung.

Dùng bởi /health (pinger ngoài), /api/cron/tick và /api/cron/warm. Một mốc thời gian
toàn cục + lock bảo đảm không spawn thread / mở connection vô tội vạ dù bị gọi dồn dập.
"""
from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

_last_warm_ts = 0.0
_lock = threading.Lock()


def warm_caches_async(min_interval: float = 120.0) -> bool:
    """Spawn 1 thread giữ ấm cache nếu đã quá ``min_interval`` giây kể từ lần gần nhất.

    Trả về True nếu đã khởi động warm, False nếu bị throttle. Không bao giờ chặn caller.
    """
    global _last_warm_ts
    now = time.time()
    with _lock:
        if now - _last_warm_ts < min_interval:
            return False
        _last_warm_ts = now

    def _run() -> None:
        try:
            from database import SessionLocal
            from compare_cache import prewarm_compare_cache

            db = SessionLocal()
            try:
                prewarm_compare_cache(db)  # đã tự prewarm Market Lab bên trong
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("Cache warm skipped: %s", e)

    threading.Thread(target=_run, daemon=True, name="cache-warm").start()
    return True
