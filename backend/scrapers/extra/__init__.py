"""Khung scrape pluggable cho NHIỀU website tour (user tự code từng site).

Mỗi site = 1 module trong `scrapers/extra/sites/` tự gọi `register(ExtraScraper(...))`.
Scrape xong ghi vào 1 tab Google Sheet CHUNG (cột "nguồn" phân biệt site) — không lưu DB.
"""
from __future__ import annotations

from .registry import ExtraScraper, get, get_all, register

__all__ = ["ExtraScraper", "get", "get_all", "register"]
