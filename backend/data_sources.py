"""Nguồn dữ liệu: Supabase/Postgres = hệ thống; Sheet = ingest/export."""
from __future__ import annotations

# Tour.canonical trong DB (Tour.id dùng chung toàn hệ thống)
DB_CANONICAL_NGUON = frozenset({"Main", "Vietravel"})

# Giá tối thiểu coi là tour HỢP LỆ (VND). Tour có gia < 10000 VND thường là:
#   - Placeholder/test data (gia = 1, 100, 1000)
#   - Đặt cọc nhầm ghi vào gia chính (gia = 5000, 10000)
#   - Liên hệ/0 đồng (scraper fallback)
# → Loại khỏi mọi tính toán So sánh VTR / phân khúc giá / route_avg / analytics
# để không làm loãng giá TB thị trường. UI vẫn hiển thị tour trong Sản phẩm & Data.
MIN_VALID_PRICE = 10_000

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
