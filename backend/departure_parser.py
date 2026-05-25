"""Parse lich_kh (lịch khởi hành) into estimated monthly departure frequency."""
from __future__ import annotations

import re
from datetime import datetime

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\b")
EXTRA_DATES_RE = re.compile(r"\(\+(\d+)\s*ngày khác\)", re.I)
WEEKDAY_RE = re.compile(r"thứ\s*(\d|cn|chủ nhật)", re.I)
PERIOD_WINDOW_DAYS = 45


def vtr_period_months(vtr_dates: list[datetime]) -> set[tuple[int, int]]:
    return {(d.year, d.month) for d in vtr_dates}


def vtr_period_label(vtr_dates: list[datetime]) -> str:
    if not vtr_dates:
        return ""
    months = sorted(vtr_period_months(vtr_dates))
    if len(months) == 1:
        y, m = months[0]
        return f"T{m}/{y}"
    y0, m0 = months[0]
    y1, m1 = months[-1]
    return f"T{m0}/{y0}–T{m1}/{y1}"


def parse_departure_dates(lich_kh: str) -> list[datetime]:
    """Trích ngày khởi hành cố định dd/mm/yyyy từ lich_kh."""
    dates: list[datetime] = []
    for m in DATE_RE.finditer(lich_kh or ""):
        parts = m.group(1).split("/")
        if len(parts) != 3:
            continue
        d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        try:
            dates.append(datetime(y, mo, d))
        except ValueError:
            continue
    return dates


def has_recurring_schedule(lich_kh: str) -> bool:
    lower = (lich_kh or "").lower()
    return "hàng ngày" in lower or "hang ngay" in lower or "theo thứ" in lower or bool(WEEKDAY_RE.search(lower))


def schedules_overlap_vtr_period(vtr_dates: list[datetime], market_lich_kh: str) -> bool:
    """
    Tour thị trường có ngày KH cùng giai đoạn với VTR:
    cùng tháng/năm hoặc trong ±45 ngày; nếu VTR chỉ có lịch theo thứ/hàng ngày thì chấp nhận lịch tương tự.
    """
    if not vtr_dates:
        return has_recurring_schedule(market_lich_kh) or bool(parse_departure_dates(market_lich_kh))

    mkt_dates = parse_departure_dates(market_lich_kh)
    if not mkt_dates:
        return has_recurring_schedule(market_lich_kh)

    vtr_months = {(d.year, d.month) for d in vtr_dates}
    for md in mkt_dates:
        if (md.year, md.month) in vtr_months:
            return True
        for vd in vtr_dates:
            if abs((md - vd).days) <= PERIOD_WINDOW_DAYS:
                return True
    return False


def parse_departure_frequency_in_period(lich_kh: str, vtr_dates: list[datetime]) -> dict:
    """Tần suất trong giai đoạn so sánh (theo tháng KH của VTR)."""
    if not vtr_dates:
        return parse_departure_frequency(lich_kh)

    months = vtr_period_months(vtr_dates)
    explicit = parse_departure_dates(lich_kh)
    in_period = [d for d in explicit if (d.year, d.month) in months]

    if in_period:
        n_months = max(len(months), 1)
        monthly = max(1.0, round(len(in_period) / n_months, 1))
        return {
            "monthly_estimate": monthly,
            "explicit_dates": len(in_period),
            "pattern": "in_vtr_period",
            "label": f"~{monthly} đoàn/tháng ({len(in_period)} ngày trong giai đoạn VTR)",
        }

    if schedules_overlap_vtr_period(vtr_dates, lich_kh):
        return parse_departure_frequency(lich_kh)

    return {
        "monthly_estimate": 0.0,
        "explicit_dates": 0,
        "pattern": "outside_period",
        "label": "Ngoài giai đoạn VTR",
    }


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
