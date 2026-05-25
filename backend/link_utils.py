"""Chuẩn hóa URL tour từ sheet/scraper."""
from __future__ import annotations

import re

_HYPERLINK_RE = re.compile(r'HYPERLINK\s*\(\s*"([^"]+)"', re.I)
_PLACEHOLDER_LABELS = frozenset({"xem chi tiết", "xem chi tiet", "link", "url"})


def normalize_tour_link(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    m = _HYPERLINK_RE.search(s)
    if m:
        s = m.group(1).strip()
    if s.lower() in _PLACEHOLDER_LABELS:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    return ""
