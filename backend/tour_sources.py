"""Nguồn tour dùng cho so sánh thị trường vs Vietravel.

FindTourGo chỉ là tab trung gian scrape → gộp vào Main trên Sheet.
Compare / Market Lab / snapshot intelligence đọc thị trường từ Main (+ Vietravel), không từ FindTourGo.
"""
from __future__ import annotations

from sqlalchemy.orm import Query

from models import Tour

# Tab scrape riêng — không dùng làm "thị trường" trong compare
MARKET_COMPARE_EXCLUDED_NGUON = frozenset({"FindTourGo"})


def apply_market_compare_source_filter(q: Query) -> Query:
    """Loại FindTourGo khỏi truy vấn dùng cho compare / market intelligence."""
    return q.filter(~Tour.nguon.in_(MARKET_COMPARE_EXCLUDED_NGUON))
