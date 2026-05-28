"""Chuẩn hóa giá trị text từ Sheet/API — tránh 'nan' làm sai coverage."""
from __future__ import annotations

_EMPTY_TOKENS = frozenset({"nan", "none", "null", "n/a", "na", "#n/a"})


def clean_text(value: str | None, *, max_len: int | None = None) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    if s.lower() in _EMPTY_TOKENS:
        return ""
    if max_len is not None:
        return s[:max_len]
    return s
