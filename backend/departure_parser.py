"""Parse lich_kh (lịch khởi hành) into estimated monthly departure frequency."""
from __future__ import annotations

import re

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\b")
EXTRA_DATES_RE = re.compile(r"\(\+(\d+)\s*ngày khác\)", re.I)
WEEKDAY_RE = re.compile(r"thứ\s*(\d|cn|chủ nhật)", re.I)


def parse_departure_frequency(lich_kh: str) -> dict:
    """
    Estimate monthly departure slots from free-text schedule.
    Tour có nhiều đoàn/ngày KH → freq_score cao hơn khi tính TB có trọng số.
    """
    text = (lich_kh or "").strip()
    if not text:
        return {
            "monthly_estimate": 1.0,
            "explicit_dates": 0,
            "pattern": "unknown",
            "label": "Chưa rõ lịch KH",
        }

    parts = [p.strip() for p in text.split("|") if p.strip()]
    explicit = 0
    extra = 0
    patterns: list[str] = []

    for part in parts:
        lower = part.lower()
        if "hàng ngày" in lower or "hang ngay" in lower or "daily" in lower:
            patterns.append("daily")
            explicit = max(explicit, 30)
            continue
        if "theo thứ" in lower or re.search(r"thứ\s*\d", lower):
            wd = len(WEEKDAY_RE.findall(part))
            if wd == 0:
                wd = 2
            patterns.append("weekly")
            explicit = max(explicit, wd * 4)
            continue

        dates = DATE_RE.findall(part)
        explicit += len(dates)
        m = EXTRA_DATES_RE.search(part)
        if m:
            extra += int(m.group(1))

    total_explicit = explicit + extra

    if "daily" in patterns:
        monthly = 30.0
    elif total_explicit >= 24:
        monthly = float(total_explicit)
    elif total_explicit >= 8:
        monthly = float(total_explicit) * 1.5
    elif total_explicit >= 4:
        monthly = float(total_explicit) * 3.0
    elif total_explicit >= 1:
        monthly = float(total_explicit) * 4.0
    elif "weekly" in patterns:
        monthly = 8.0
    else:
        monthly = 2.0

    monthly = max(1.0, min(monthly, 60.0))

    if "daily" in patterns:
        label = "Hàng ngày (~30 lượt/tháng)"
    elif total_explicit > 0:
        label = f"~{int(monthly)} lượt KH/tháng ({total_explicit} ngày liệt kê)"
    elif "weekly" in patterns:
        label = f"Theo thứ (~{int(monthly)} lượt/tháng)"
    else:
        label = f"Ước tính ~{int(monthly)} lượt/tháng"

    return {
        "monthly_estimate": round(monthly, 1),
        "explicit_dates": total_explicit,
        "pattern": patterns[0] if patterns else ("fixed" if total_explicit else "unknown"),
        "label": label,
    }
