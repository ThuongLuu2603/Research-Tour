"""Nguồn dữ liệu: Supabase/Postgres = hệ thống; Sheet = ingest/export."""
from __future__ import annotations

# Tour.canonical trong DB (Tour.id dùng chung toàn hệ thống)
DB_CANONICAL_NGUON = frozenset({"Main", "Vietravel"})

# Chỉ Google Sheet — không ghi tours
SHEET_ONLY_NGUON = frozenset({"FindTourGo"})

# Tab Sheet ↔ nguồn (FindTourGo vẫn có tab để đọc tham khảo / scraper)
ALL_SHEET_TABS = frozenset({"Main", "Vietravel", "FindTourGo"})


def is_db_canonical_source(nguon: str) -> bool:
    return nguon in DB_CANONICAL_NGUON


def is_sheet_only_source(nguon: str) -> bool:
    return nguon in SHEET_ONLY_NGUON


def should_mirror_prune(nguon: str) -> bool:
    """Xóa tour DB không còn trên nguồn ingest (Main / Vietravel)."""
    return nguon in DB_CANONICAL_NGUON
