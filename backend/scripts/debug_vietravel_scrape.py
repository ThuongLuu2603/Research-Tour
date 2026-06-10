"""Chẩn đoán scrape Vietravel qua API JSON (api2.travel.com.vn).

Vietravel đã đổi web sang SPA → data lấy qua API JSON, KHÔNG còn nhúng HTML.
Bản HTML-scrape cũ (regex pageId/salePrice/heuristic deposit) đã chết và bị gỡ.
Script này dùng `fetch_tours_from_api()` mới để in N tour đầu của mỗi keyword,
phục vụ kiểm tra giá / dòng tour / điểm KH / thời gian / lịch KH.

CÁCH CHẠY (trong thư mục backend):
    python scripts/debug_vietravel_scrape.py
        → quét cả 2 keyword (viet-nam, nuoc-ngoai), in 8 tour đầu mỗi keyword.

    python scripts/debug_vietravel_scrape.py viet-nam
        → chỉ 1 keyword.

    python scripts/debug_vietravel_scrape.py viet-nam 20
        → tham số thứ 2 = số tour tối đa in ra (mặc định 8).

KHÔNG ghi DB, KHÔNG ghi Sheet — chỉ gọi API & in.
"""

from __future__ import annotations

import os
import sys

# Cho phép chạy từ bất kỳ đâu: thêm thư mục backend vào sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from scrapers.vietravel_scraper import (  # noqa: E402
    MARKETS,
    fetch_tours_from_api,
)


def _print_tour(t: dict, idx: int) -> None:
    print("=" * 78)
    print(f"[{idx}] {t.get('ten_tour', '')}")
    print(f"    link:       {t.get('link_url', '')}")
    print(f"    mã tour:    {t.get('page_code', '')}   (pageId={t.get('page_id', '')})")
    print(f"    dòng tour:  {t.get('dong_tour', '')!r}")
    print(f"    điểm KH:    {t.get('diem_kh', '')!r}")
    print(f"    thời gian:  {t.get('thoi_gian', '')!r}")
    print(f"    giá:        {t.get('gia', '')!r}")
    lk = t.get("lich_kh", "") or ""
    print(f"    lịch KH:    {lk[:90]!r}{'…' if len(lk) > 90 else ''}")
    print(f"    khách sạn:  {t.get('khach_san', '')!r}")


def main() -> None:
    args = sys.argv[1:]
    keywords = [args[0]] if args else [kw for kw, _ in MARKETS]
    try:
        limit = int(args[1]) if len(args) > 1 else 8
    except ValueError:
        limit = 8

    for keyword in keywords:
        print("\n" + "#" * 78)
        print(f"# KEYWORD: {keyword!r}")
        print("#" * 78)
        tours = fetch_tours_from_api(keyword)
        print(f"→ Tổng {len(tours)} tour (sau dedup). In {min(limit, len(tours))} tour đầu:\n")
        for i, t in enumerate(tours[:limit], 1):
            _print_tour(t, i)
        if not tours:
            print("❌ 0 tour — token hết hạn / keyword không nhận / API đổi. Xem log warning.")


if __name__ == "__main__":
    main()
