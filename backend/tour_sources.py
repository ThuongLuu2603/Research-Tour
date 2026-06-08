"""Nguồn tour dùng cho so sánh thị trường vs Vietravel.

- Thị trường / đối thủ: chỉ tab Main (FindTourGo là pipeline trung gian).
- Vietravel so sánh: chỉ tab scrape Vietravel (`nguon=Vietravel`), không theo tên CTY trên Main.
"""
from __future__ import annotations

from sqlalchemy.orm import Query

from models import Tour

MARKET_COMPARE_EXCLUDED_NGUON = frozenset({"FindTourGo"})


def apply_market_compare_source_filter(q: Query) -> Query:
    """Loại FindTourGo + market 'Không xác định' khỏi truy vấn compare/market.

    System-wide rule: tour với thi_truong="Không xác định" không tham gia mọi
    calculation/insight/report (xem tour_filters.EXCLUDED_MARKETS).
    """
    from tour_filters import market_filter_clause
    return q.filter(
        ~Tour.nguon.in_(MARKET_COMPARE_EXCLUDED_NGUON),
        market_filter_clause(Tour),
    )


def is_vietravel_tab(t: Tour) -> bool:
    """Tour thuộc tab scrape Vietravel — nguồn duy nhất cho KPI & nhóm VTR."""
    return (t.nguon or "") == "Vietravel" or (t.sheet_source or "") == "Vietravel"


def _company_is_vietravel_label(cong_ty: str) -> bool:
    from classification import resolve_company_name
    from config import settings

    resolved = resolve_company_name(cong_ty or "")
    return settings.company_name.lower() in resolved.lower()


def is_phantom_vietravel_on_catalog(t: Tour) -> bool:
    """Nhãn công ty Vietravel trên Main/khác — user xác nhận Main không có VTR; loại khỏi compare."""
    if is_vietravel_tab(t):
        return False
    return _company_is_vietravel_label(t.cong_ty or "")


def filter_tours_for_market_compare(tours: list[Tour]) -> list[Tour]:
    """Dataset compare: không FTG, không VTR ảo trên Main, không tour placeholder FIT,
    không market 'Không xác định'."""
    from tour_stats_exclusions import filter_tours_for_statistics
    from tour_filters import is_excluded_market

    return filter_tours_for_statistics([
        t for t in tours
        if not is_phantom_vietravel_on_catalog(t)
        and not is_excluded_market(t.thi_truong)
    ])


def apply_analytics_tour_filters(q: Query) -> Query:
    """Nguồn compare + loại tour placeholder FIT (SQL)."""
    from tour_stats_exclusions import apply_stats_exclusion_query

    return apply_stats_exclusion_query(apply_market_compare_source_filter(q))
