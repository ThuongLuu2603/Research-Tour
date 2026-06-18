"""Lễ hội âm lịch VN — long-range planner (T3 Phase 3, UC #7).

Lễ âm lịch lặp lại mỗi năm âm nhưng dương lịch dịch ngày → khó plan booking
nếu chỉ dựa vào festival scrape (vietnam.travel chỉ liệt 12-18 tháng tới).

Module này có:
  1. Static catalog: 12 lễ âm lịch quan trọng (Tết, Rằm tháng Giêng, Giỗ Tổ,
     Vu Lan, Trung Thu, Tết Nguyên Tiêu, ...).
  2. Auto-expand 3-5 năm tới qua hàm lunar→solar (dùng thuật toán Hồ Ngọc Đức
     đơn giản hoặc lookup table).
  3. Upsert vào festivals table (is_lunar=True) để timeline + tagging tự cover.

Phase 3 dùng lookup table hardcoded (1 file ngắn). Phase sau có thể dùng
lib `lunardate` (~5KB) hoặc `lunarcalendar` để tự compute.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── Âm → Dương lịch: thuật toán Hồ Ngọc Đức (timezone VN = +7) ────────────────
# Wave 7: bỏ bảng tra cứng (chỉ phủ 2025-2030, dễ lỗi thời) → TÍNH TỰ ĐỘNG cho
# mọi năm. Thuật toán thiên văn chuẩn cho âm lịch VN, public-domain, không cần
# pip dependency (lunardate là âm lịch TQ múi +8, lệch 1 ngày vài dịp).
_TZ = 7.0


def _jd_from_date(dd: int, mm: int, yy: int) -> int:
    a = (14 - mm) // 12
    y = yy + 4800 - a
    m = mm + 12 * a - 3
    jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    if jd < 2299161:
        jd = dd + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    return jd


def _jd_to_date(jd: int) -> tuple[int, int, int]:
    if jd > 2299160:
        a = jd + 32044
        b = (4 * a + 3) // 146097
        c = a - (b * 146097) // 4
    else:
        b = 0
        c = jd + 32082
    d = (4 * c + 3) // 1461
    e = c - (1461 * d) // 4
    m = (5 * e + 2) // 153
    day = e - (153 * m + 2) // 5 + 1
    month = m + 3 - 12 * (m // 10)
    year = b * 100 + d - 4800 + m // 10
    return (day, month, year)


def _new_moon(k: int) -> float:
    T = k / 1236.85
    T2 = T * T
    T3 = T2 * T
    dr = math.pi / 180
    Jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3
    Jd1 += 0.00033 * math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr)
    M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3
    Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3
    F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3
    C1 = (0.1734 - 0.000393 * T) * math.sin(M * dr) + 0.0021 * math.sin(2 * dr * M)
    C1 += -0.4068 * math.sin(Mpr * dr) + 0.0161 * math.sin(dr * 2 * Mpr)
    C1 += -0.0004 * math.sin(dr * 3 * Mpr)
    C1 += 0.0104 * math.sin(dr * 2 * F) - 0.0051 * math.sin(dr * (M + Mpr))
    C1 += -0.0074 * math.sin(dr * (M - Mpr)) + 0.0004 * math.sin(dr * (2 * F + M))
    C1 += -0.0004 * math.sin(dr * (2 * F - M)) - 0.0006 * math.sin(dr * (2 * F + Mpr))
    C1 += 0.0010 * math.sin(dr * (2 * F - Mpr)) + 0.0005 * math.sin(dr * (2 * Mpr + M))
    if T < -11:
        deltat = 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3
    else:
        deltat = -0.000278 + 0.000265 * T + 0.000262 * T2
    return Jd1 + C1 - deltat


def _new_moon_day(k: int) -> int:
    return int(_new_moon(k) + 0.5 + _TZ / 24.0)


def _sun_longitude(jdn: float) -> float:
    T = (jdn - 2451545.0) / 36525.0
    T2 = T * T
    dr = math.pi / 180
    M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2
    L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2
    DL = (1.914600 - 0.004817 * T - 0.000014 * T2) * math.sin(dr * M)
    DL += (0.019993 - 0.000101 * T) * math.sin(dr * 2 * M) + 0.000290 * math.sin(dr * 3 * M)
    L = (L0 + DL) * dr
    L = L - math.pi * 2 * int(L / (math.pi * 2))
    return L


def _sun_longitude_month(day_number: int) -> int:
    return int(_sun_longitude(day_number - 0.5 - _TZ / 24.0) / math.pi * 6)


def _lunar_month_11(yy: int) -> int:
    off = _jd_from_date(31, 12, yy) - 2415021
    k = int(off / 29.530588853)
    nm = _new_moon_day(k)
    if _sun_longitude_month(nm) >= 9:
        nm = _new_moon_day(k - 1)
    return nm


def _leap_month_offset(a11: int) -> int:
    k = int((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = _sun_longitude_month(_new_moon_day(k + i))
    while True:
        last = arc
        i += 1
        arc = _sun_longitude_month(_new_moon_day(k + i))
        if not (arc != last and i < 14):
            break
    return i - 1


def convert_lunar_to_solar(lunar_d: int, lunar_m: int, lunar_y: int, leap: int = 0) -> date | None:
    """Âm → dương lịch (VN, +7). Trả None nếu (tháng nhuận) không tồn tại năm đó."""
    if lunar_m < 11:
        a11 = _lunar_month_11(lunar_y - 1)
        b11 = _lunar_month_11(lunar_y)
    else:
        a11 = _lunar_month_11(lunar_y)
        b11 = _lunar_month_11(lunar_y + 1)
    off = lunar_m - 11
    if off < 0:
        off += 12
    if b11 - a11 > 365:
        leap_off = _leap_month_offset(a11)
        leap_month = leap_off - 2
        if leap_month < 0:
            leap_month += 12
        if leap != 0 and lunar_m != leap_month:
            return None
        if leap != 0 or off >= leap_off:
            off += 1
    k = int(0.5 + (a11 - 2415021.076998695) / 29.530588853)
    month_start = _new_moon_day(k + off)
    dd, mm, yy = _jd_to_date(month_start + lunar_d - 1)
    return date(yy, mm, dd)


# Khoảng năm âm lịch tự sinh (rộng → planner 3-5 năm luôn có dữ liệu, kể cả
# lễ cuối năm rơi sang dương lịch năm sau). Tính 1 lần lúc import (rẻ).
_LUNAR_YEAR_FROM = 2024
_LUNAR_YEAR_TO = 2035

# Metadata cho mỗi lễ âm
LUNAR_FESTIVAL_META: dict[tuple[int, int], dict[str, str]] = {
    (1, 1):  {"name": "Tết Nguyên Đán",         "category": "cultural",  "region": "", "duration_days": "3"},
    (1, 15): {"name": "Tết Nguyên Tiêu (Rằm Tháng Giêng)", "category": "religious", "region": "", "duration_days": "1"},
    (3, 3):  {"name": "Tết Hàn Thực",            "category": "cultural",  "region": "", "duration_days": "1"},
    (3, 10): {"name": "Giỗ Tổ Hùng Vương",      "category": "cultural",  "region": "bac", "duration_days": "1"},
    (4, 8):  {"name": "Lễ Phật Đản",             "category": "religious", "region": "", "duration_days": "1"},
    (5, 5):  {"name": "Tết Đoan Ngọ",            "category": "cultural",  "region": "", "duration_days": "1"},
    (7, 7):  {"name": "Thất Tịch (Ngưu Lang Chức Nữ)", "category": "cultural", "region": "", "duration_days": "1"},
    (7, 15): {"name": "Vu Lan Báo Hiếu",        "category": "religious", "region": "", "duration_days": "1"},
    (8, 15): {"name": "Tết Trung Thu",           "category": "cultural",  "region": "", "duration_days": "1"},
    (9, 9):  {"name": "Tết Trùng Cửu",           "category": "cultural",  "region": "", "duration_days": "1"},
    (10, 10): {"name": "Tết Hạ Nguyên",          "category": "cultural",  "region": "", "duration_days": "1"},
    (12, 23): {"name": "Tết Ông Công Ông Táo",  "category": "cultural",  "region": "", "duration_days": "1"},
}


def _build_lunar_to_solar() -> dict[tuple[int, int, int], date]:
    """Sinh bảng {(năm âm, tháng âm, ngày âm): ngày dương} cho mọi lễ × dải năm.

    Key năm = NĂM ÂM LỊCH (vd Ông Táo 23/12 âm năm 2025 → rơi ~02/2026 dương).
    Tính tự động bằng convert_lunar_to_solar → không còn phụ thuộc bảng cứng.
    """
    table: dict[tuple[int, int, int], date] = {}
    for yr in range(_LUNAR_YEAR_FROM, _LUNAR_YEAR_TO + 1):
        for (lm, ld) in LUNAR_FESTIVAL_META:
            solar = convert_lunar_to_solar(ld, lm, yr)
            if solar is not None:
                table[(yr, lm, ld)] = solar
    return table


# Tính 1 lần lúc import — vài trăm phép biến đổi, rẻ.
LUNAR_TO_SOLAR: dict[tuple[int, int, int], date] = _build_lunar_to_solar()


def _compute_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def seed_lunar_festivals(db) -> dict[str, int]:
    """Upsert lễ âm lịch vào festivals table.

    Hash-based: skip nếu đã có. Trả stats.
    """
    from models import Festival

    inserted = 0
    skipped = 0
    now = datetime.utcnow()
    for (yr, lm, ld), date_duong in LUNAR_TO_SOLAR.items():
        meta = LUNAR_FESTIVAL_META.get((lm, ld))
        if not meta:
            continue
        slug = f"lunar-{lm:02d}-{ld:02d}-{yr}"
        existing = db.query(Festival).filter(Festival.slug == slug).first()
        try:
            duration = int(meta.get("duration_days", "1"))
        except ValueError:
            duration = 1
        date_end = date(date_duong.year, date_duong.month, date_duong.day)
        if duration > 1:
            from datetime import timedelta
            date_end = date_duong + timedelta(days=duration - 1)
        content_hash = _compute_hash(meta["name"], str(date_duong), str(date_end))
        if existing:
            if existing.content_hash == content_hash:
                skipped += 1
                continue
            existing.name_vi = meta["name"]
            existing.date_start = date_duong
            existing.date_end = date_end
            existing.is_lunar = True
            existing.lunar_month = lm
            existing.lunar_day = ld
            existing.category = meta["category"]
            existing.region = meta["region"]
            existing.description = f"Lễ âm lịch {lm:02d}/{ld:02d} (năm {yr})"
            existing.content_hash = content_hash
            existing.scraped_at = now
        else:
            f = Festival(
                slug=slug,
                name_vi=meta["name"],
                date_start=date_duong,
                date_end=date_end,
                is_lunar=True,
                lunar_month=lm,
                lunar_day=ld,
                category=meta["category"],
                region=meta["region"],
                description=f"Lễ âm lịch {lm:02d}/{ld:02d} (năm {yr})",
                source_url="https://am-duong.com",
                content_hash=content_hash,
                scraped_at=now,
            )
            db.add(f)
            inserted += 1
    db.commit()
    logger.info("Lunar festivals seed: inserted=%d skipped=%d", inserted, skipped)
    if inserted:
        try:
            from redis_cache import redis_invalidate_pattern
            redis_invalidate_pattern("ota:festival.*")
        except Exception:  # noqa: BLE001
            pass
    return {"inserted": inserted, "skipped": skipped}


def get_lunar_planner(db, years_ahead: int = 3) -> list[dict[str, Any]]:
    """Lịch âm lịch dương hóa cho N năm tới — dùng cho long-range tour planner."""
    from models import Festival

    today_year = date.today().year
    until_year = today_year + years_ahead
    rows = (
        db.query(Festival)
        .filter(Festival.is_lunar == True)  # noqa: E712
        .filter(Festival.date_start >= date(today_year, 1, 1))
        .filter(Festival.date_start <= date(until_year, 12, 31))
        .order_by(Festival.date_start.asc())
        .all()
    )
    return [
        {
            "slug": f.slug,
            "name": f.name_vi,
            "date_start": f.date_start.isoformat(),
            "date_end": f.date_end.isoformat(),
            "lunar_month": f.lunar_month,
            "lunar_day": f.lunar_day,
            "category": f.category,
            "region": f.region,
            "year": f.date_start.year,
        }
        for f in rows
    ]
