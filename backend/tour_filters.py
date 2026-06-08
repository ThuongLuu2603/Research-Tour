"""Helper filters cho Tour query — shared across modules.

Cung cấp các filter chung dùng trong analytics, reports, insight engines để
đảm bảo consistency: cùng 1 loại tour bị loại trừ ở mọi nơi.
"""
from __future__ import annotations

# Các giá trị thi_truong bị loại trừ KHỎI MỌI tính toán/báo cáo/insight.
# User quyết định: tour với thi_truong nằm trong set này = "không tồn tại" cho
# mọi mục đích phân tích. Vẫn lưu DB nhưng không tham gia stats/compare/charts.
EXCLUDED_MARKETS: frozenset[str] = frozenset({
    "Không xác định",
    "Khong xac dinh",
    "Chưa xác định",
    "Chua xac dinh",
})


def excluded_market_values() -> list[str]:
    """List values dùng cho SQL NOT IN. Trả list để SQLAlchemy in_() chấp nhận."""
    return list(EXCLUDED_MARKETS)


def apply_market_filter(query, Tour):
    """Apply filter loại trừ market "Không xác định" cho 1 SQLAlchemy query.

    Args:
        query: SQLAlchemy query object
        Tour: models.Tour class

    Returns:
        Query đã thêm filter Tour.thi_truong NOT IN excluded.

    Lưu ý: dùng `notin_` với explicit list để tránh issue NULL semantics
    (NULL NOT IN [...] = NULL trong SQL; thêm coalesce hoặc OR is_null).
    """
    return query.filter(
        (Tour.thi_truong.is_(None)) | (~Tour.thi_truong.in_(excluded_market_values()))
    )


def market_filter_clause(Tour):
    """Trả chỉ clause filter (không apply vào query) — để gộp với other filters.

    Vd: db.query(Tour).filter(market_filter_clause(Tour), Tour.gia.isnot(None))
    """
    return (Tour.thi_truong.is_(None)) | (~Tour.thi_truong.in_(excluded_market_values()))


def is_excluded_market(thi_truong: str | None) -> bool:
    """Python-level check: tour có thi_truong này có bị loại không?"""
    if not thi_truong:
        return False  # NULL/empty không bị loại (chỉ loại explicit "Không xác định")
    return thi_truong.strip() in EXCLUDED_MARKETS
