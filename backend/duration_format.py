"""Chuẩn hiển thị / parse thời gian tour dạng NĐ (VD: 5N4Đ → 5, 5N5Đ → 5.5, 0.5N → 0.5)."""
from __future__ import annotations

import re


def format_duration_label(days: float | None) -> str:
    """Số ngày chuẩn → nhãn NĐ."""
    if days is None:
        return "—"
    d = round(float(days), 2)
    if abs(d - 0.5) < 0.01:
        return "0.5N"
    n = int(d)
    frac = round(d - n, 2)
    if abs(frac - 0.5) < 0.01 and n >= 1:
        return f"{n}N{n}\u0110"
    if abs(frac) < 0.01 and n >= 1:
        if n == 1:
            return "1N"
        return f"{n}N{n - 1}\u0110"
    if abs(frac) < 0.01:
        return f"{n}N"
    return f"{d}N"


def parse_duration_nd(text: str) -> float | None:
    """
    Parse nhãn NĐ hoặc alias dạng 5N4Đ, 5n4d, 1N, 0.5N.
    Quy ước giá trị:
      - 5N4Đ → 5
      - 5N5Đ → 5.5
      - 1N → 1
      - 0.5N → 0.5
    """
    s = re.sub(r"\s+", "", (text or "").strip().lower())
    s = s.replace("đ", "d")
    if not s:
        return None

    m = re.match(r"^(\d+(?:\.\d+)?)n(\d+)d$", s)
    if m:
        n, d = float(m.group(1)), int(m.group(2))
        if abs(n - int(n)) < 0.01 and d == int(n):
            return n + 0.5
        return n

    m = re.match(r"^(\d+(?:\.\d+)?)n$", s)
    if m:
        v = float(m.group(1))
        return v if 0 < v <= 45 else None

    try:
        v = float(s.replace(",", "."))
        return v if 0 < v <= 45 else None
    except ValueError:
        return None


def parse_duration_input(text: str) -> float | None:
    """Ô nhập admin: ưu tiên NĐ, sau đó số thuần."""
    return parse_duration_nd(text)
