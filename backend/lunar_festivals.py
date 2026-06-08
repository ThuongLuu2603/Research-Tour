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
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Lookup table: lễ âm → dương lịch cho 2025-2030.
# Format: {(year_duong, lunar_month, lunar_day): date_duong}
# Data nguồn: âm lịch VN chính thức (https://am-duong.com).
# 12 lễ chính được expand cho 6 năm = 72 entries.
LUNAR_TO_SOLAR: dict[tuple[int, int, int], date] = {
    # 2025
    (2025, 1, 1): date(2025, 1, 29),   # Tết Nguyên Đán
    (2025, 1, 15): date(2025, 2, 12),  # Rằm tháng Giêng (Nguyên Tiêu)
    (2025, 3, 3): date(2025, 3, 31),   # Tết Hàn Thực
    (2025, 3, 10): date(2025, 4, 7),   # Giỗ Tổ Hùng Vương
    (2025, 4, 8): date(2025, 5, 5),    # Phật Đản
    (2025, 5, 5): date(2025, 5, 31),   # Tết Đoan Ngọ
    (2025, 7, 7): date(2025, 8, 30),   # Thất Tịch (Ngưu Lang Chức Nữ)
    (2025, 7, 15): date(2025, 9, 6),   # Vu Lan
    (2025, 8, 15): date(2025, 10, 6),  # Trung Thu
    (2025, 9, 9): date(2025, 10, 29),  # Trùng Cửu
    (2025, 10, 10): date(2025, 11, 29), # Tết Hạ Nguyên
    (2025, 12, 23): date(2026, 2, 10), # Ông Công Ông Táo
    # 2026
    (2026, 1, 1): date(2026, 2, 17),   # Tết Nguyên Đán
    (2026, 1, 15): date(2026, 3, 3),
    (2026, 3, 3): date(2026, 4, 19),
    (2026, 3, 10): date(2026, 4, 26),
    (2026, 4, 8): date(2026, 5, 24),
    (2026, 5, 5): date(2026, 6, 19),
    (2026, 7, 7): date(2026, 8, 19),
    (2026, 7, 15): date(2026, 8, 27),
    (2026, 8, 15): date(2026, 9, 25),
    (2026, 9, 9): date(2026, 10, 19),
    (2026, 10, 10): date(2026, 11, 19),
    (2026, 12, 23): date(2027, 1, 30),
    # 2027
    (2027, 1, 1): date(2027, 2, 6),
    (2027, 1, 15): date(2027, 2, 20),
    (2027, 3, 3): date(2027, 4, 8),
    (2027, 3, 10): date(2027, 4, 15),
    (2027, 4, 8): date(2027, 5, 13),
    (2027, 5, 5): date(2027, 6, 9),
    (2027, 7, 7): date(2027, 8, 8),
    (2027, 7, 15): date(2027, 8, 16),
    (2027, 8, 15): date(2027, 9, 15),
    (2027, 9, 9): date(2027, 10, 8),
    (2027, 10, 10): date(2027, 11, 8),
    (2027, 12, 23): date(2028, 1, 19),
    # 2028
    (2028, 1, 1): date(2028, 1, 26),
    (2028, 1, 15): date(2028, 2, 9),
    (2028, 3, 3): date(2028, 3, 28),
    (2028, 3, 10): date(2028, 4, 4),
    (2028, 4, 8): date(2028, 5, 2),
    (2028, 5, 5): date(2028, 5, 28),
    (2028, 7, 7): date(2028, 8, 26),
    (2028, 7, 15): date(2028, 9, 3),
    (2028, 8, 15): date(2028, 10, 3),
    (2028, 9, 9): date(2028, 10, 26),
    (2028, 10, 10): date(2028, 11, 26),
    (2028, 12, 23): date(2029, 2, 6),
    # 2029
    (2029, 1, 1): date(2029, 2, 13),
    (2029, 1, 15): date(2029, 2, 27),
    (2029, 3, 3): date(2029, 4, 16),
    (2029, 3, 10): date(2029, 4, 23),
    (2029, 4, 8): date(2029, 5, 21),
    (2029, 5, 5): date(2029, 6, 16),
    (2029, 7, 7): date(2029, 8, 16),
    (2029, 7, 15): date(2029, 8, 24),
    (2029, 8, 15): date(2029, 9, 22),
    (2029, 9, 9): date(2029, 10, 16),
    (2029, 10, 10): date(2029, 11, 16),
    (2029, 12, 23): date(2030, 1, 27),
    # 2030
    (2030, 1, 1): date(2030, 2, 3),
    (2030, 1, 15): date(2030, 2, 17),
    (2030, 3, 3): date(2030, 4, 6),
    (2030, 3, 10): date(2030, 4, 13),
    (2030, 4, 8): date(2030, 5, 10),
    (2030, 5, 5): date(2030, 6, 5),
    (2030, 7, 7): date(2030, 8, 5),
    (2030, 7, 15): date(2030, 8, 13),
    (2030, 8, 15): date(2030, 9, 12),
    (2030, 9, 9): date(2030, 10, 5),
    (2030, 10, 10): date(2030, 11, 5),
    (2030, 12, 23): date(2031, 1, 16),
}

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
