"""Nguồn tour dùng cho so sánh thị trường vs Vietravel.

- Thị trường / đối thủ: chỉ tab Main (FindTourGo là pipeline trung gian).
- Vietravel so sánh: chỉ tab scrape Vietravel (`nguon=Vietravel`), không theo tên CTY trên Main.
"""
from __future__ import annotations

from sqlalchemy.orm import Query

from models import Tour

MARKET_COMPARE_EXCLUDED_NGUON = frozenset({"FindTourGo"})


def apply_market_compare_source_filter(q: Query) -> Query:
    """Loại FindTourGo khỏi truy vấn dùng cho compare / market intelligence."""
    return q.filter(~Tour.nguon.in_(MARKET_COMPARE_EXCLUDED_NGUON))


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
    """Dataset compare: không FTG, không 'Vietravel' ảo trên catalog Main."""
    return [t for t in tours if not is_phantom_vietravel_on_catalog(t)]
