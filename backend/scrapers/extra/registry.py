"""Registry các extra scraper site (user tự code).

Khi import module này, MỌI module trong `scrapers/extra/sites/` được auto-import
(pkgutil.iter_modules) → mỗi site tự gọi `register(...)` ở top-level.

User thêm site mới: copy `sites/example_site.py` → đổi `key`/`name` → viết `scrape()` →
gọi `register(ExtraScraper(...))`. Không cần sửa file nào khác.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ExtraScraper:
    key: str            # định danh duy nhất (vd "dulichviet") — dùng làm cột "nguồn" trên Sheet
    name: str           # tên hiển thị trên UI
    scrape: Callable[..., "pd.DataFrame"]  # (progress=None) -> DataFrame chuẩn cột giống findtourgo
    timeout_sec: int = 2700


_REGISTRY: dict[str, ExtraScraper] = {}


def register(s: ExtraScraper) -> None:
    """Đăng ký 1 site. Gọi từ top-level mỗi module trong sites/."""
    if not s.key:
        raise ValueError("ExtraScraper.key không được rỗng")
    if s.key in _REGISTRY:
        logger.warning("Extra scraper '%s' đã đăng ký — ghi đè", s.key)
    _REGISTRY[s.key] = s


def get_all() -> list[ExtraScraper]:
    return list(_REGISTRY.values())


def get(key: str) -> ExtraScraper | None:
    return _REGISTRY.get(key)


def _autoload_sites() -> None:
    """Import mọi module trong scrapers/extra/sites/ → trigger register() của từng site."""
    try:
        from . import sites
    except Exception as e:  # noqa: BLE001
        logger.warning("Không import được package sites/: %s", e)
        return
    for mod in pkgutil.iter_modules(sites.__path__):
        if mod.name.startswith("_"):
            continue
        full = f"{sites.__name__}.{mod.name}"
        try:
            importlib.import_module(full)
        except Exception as e:  # noqa: BLE001
            # 1 site lỗi import KHÔNG được chặn các site khác / cả app.
            logger.exception("Lỗi import extra site %s: %s", full, e)


_autoload_sites()
