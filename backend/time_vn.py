"""Giờ Việt Nam (GMT+7) — dùng cho MỌI mốc thời gian hiển thị / ghi ra Google Sheet.

Render chạy theo UTC; `datetime.now()`/`utcnow()` đều ra UTC → lệch 7 tiếng so với VN.
VN không có DST nên dùng offset cố định +7 (không cần gói tzdata).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7), name="ICT")  # Asia/Ho_Chi_Minh, cố định +7


def now_vn() -> datetime:
    """Thời điểm hiện tại theo giờ VN (tz-aware)."""
    return datetime.now(VN_TZ)


def to_vn(dt: datetime | None) -> datetime | None:
    """Đổi 1 datetime sang giờ VN. Naive coi như UTC (DB lưu utcnow())."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(VN_TZ)


def fmt_vn(dt: datetime | None = None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Format theo giờ VN. dt=None → hiện tại; dt naive → coi là UTC."""
    target = now_vn() if dt is None else to_vn(dt)
    return target.strftime(fmt) if target else ""
