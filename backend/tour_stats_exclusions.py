"""Loại tour placeholder / FIT khỏi KPI, compare, snapshot, admin gap queue.

Cùng tên tour vẫn lưu trong DB & Research Grid; chỉ không tính vào thống kê.
Bổ sung pattern trong DEFAULT_TITLE_EXCLUDE_SUBSTRINGS hoặc gọi add_runtime_exclusion().
"""
from __future__ import annotations

import re
import unicodedata

from models import Tour

# Chuỗi con trong ten_tour (không phân biệt hoa thường, có/không dấu).
DEFAULT_TITLE_EXCLUDE_SUBSTRINGS: tuple[str, ...] = (
    "tạm chưa có giá",
    "tam chua co gia",
    "đoàn riêng",
    "doan rieng",
    "du lịch nước ngoài :",
    "du lich nuoc ngoai :",
    "catalog placeholder",
    "chưa có giá tour",
    "chua co gia tour",
)

_runtime_extra: list[str] = []


def add_runtime_exclusion(substring: str) -> None:
    """Thêm pattern khi chạy (test / script); không persist DB."""
    s = substring.strip().lower()
    if s and s not in _runtime_extra:
        _runtime_extra.append(s)


def all_exclusion_substrings() -> tuple[str, ...]:
    return DEFAULT_TITLE_EXCLUDE_SUBSTRINGS + tuple(_runtime_extra)


def _fold_vi(s: str) -> str:
    from text_fold import fold_vi

    return fold_vi(s)


def is_fit_placeholder_title(title: str) -> bool:
    low = _fold_vi(title)
    if not low:
        return True
    for p in all_exclusion_substrings():
        if p in low:
            return True
    if re.match(r"^\([^)]*(chưa có giá|chua co gia)[^)]*\)\s*$", low):
        return True
    return False


def is_stats_excluded_tour(t: Tour) -> bool:
    return is_fit_placeholder_title(t.ten_tour or "")


def filter_tours_for_statistics(tours: list[Tour]) -> list[Tour]:
    return [t for t in tours if not is_stats_excluded_tour(t)]


def apply_stats_exclusion_query(q):
    """SQLAlchemy Query — loại tour có ten_tour chứa pattern loại trừ."""
    from models import Tour

    for p in all_exclusion_substrings():
        q = q.filter(~Tour.ten_tour.ilike(f"%{p}%"))
    return q
