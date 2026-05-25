"""Stable tour IDs for Sheet ↔ DB ↔ workspace overrides."""
from __future__ import annotations

import hashlib
import re

_PLACEHOLDER_LINKS = frozenset({"xem chi tiết", "xem chi tiet", "xem", ""})


def _slug(text: str, max_len: int = 80) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    return s[:max_len].replace(" ", "-")


def compute_external_id(
    nguon: str,
    *,
    ma_tour: str = "",
    link_url: str = "",
    ten_tour: str = "",
) -> str:
    src = (nguon or "Unknown").strip()
    ma = (ma_tour or "").strip()
    if ma:
        return f"{src}:{ma}"

    link = (link_url or "").strip()
    if link:
        try:
            from link_utils import normalize_tour_link
            link = normalize_tour_link(link)
        except Exception:
            pass
    low = link.lower()
    if link and low not in _PLACEHOLDER_LINKS and link.startswith("http"):
        base = link.split("?")[0]
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
        return f"{src}:link:{digest}"

    name = _slug(ten_tour)
    if name:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
        return f"{src}:name:{digest}"

    digest = hashlib.sha256((ten_tour or src).encode("utf-8")).hexdigest()[:12]
    return f"{src}:unknown:{digest}"


def compute_content_hash(fields: dict) -> str:
    keys = (
        "cong_ty", "thi_truong", "tuyen_tour", "ten_tour", "gia_raw",
        "lich_kh", "link_url", "ma_tour", "thoi_gian", "diem_kh",
    )
    payload = "|".join(str(fields.get(k, "") or "") for k in keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
