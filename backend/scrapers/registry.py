"""Registry scraper — mở rộng nguồn OTA/đối thủ."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ScraperSpec:
    name: str
    label: str
    description: str
    nguon: str
    enabled: bool = True
    run_fn: Callable | None = None


_REGISTRY: dict[str, ScraperSpec] = {}


def register(spec: ScraperSpec) -> None:
    _REGISTRY[spec.name] = spec


def list_scrapers() -> list[dict]:
    return [
        {
            "name": s.name,
            "label": s.label,
            "description": s.description,
            "nguon": s.nguon,
            "enabled": s.enabled,
        }
        for s in _REGISTRY.values()
    ]


def get_scraper(name: str) -> ScraperSpec | None:
    return _REGISTRY.get(name)


def _bootstrap():
    register(ScraperSpec(
        name="vietravel",
        label="Vietravel",
        description="Scrape travel.com.vn — tour VTR",
        nguon="Vietravel",
    ))
    register(ScraperSpec(
        name="findtourgo",
        label="FindTourGo",
        description="API aggregator — thị trường & đối thủ",
        nguon="FindTourGo",
    ))
    register(ScraperSpec(
        name="ota_placeholder",
        label="OTA mới (sắp có)",
        description="Khung mở rộng — thêm scraper đối thủ/OTA: implement class + register()",
        nguon="OTA",
        enabled=False,
    ))


_bootstrap()
