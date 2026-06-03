"""Chuẩn hóa tiếng Việt — so khớp không phân biệt dấu."""
from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def fold_vi(text: str) -> str:
    """
    Bỏ dấu + chữ thường + gộp khoảng trắng.
    «Chùa Tam Chúc» và «chua tam chuc» → «chua tam chuc».
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text).strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    s = _WHITESPACE.sub(" ", s.lower())
    return s.strip()[:8000]
