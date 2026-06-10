"""Chẩn đoán scrape Vietravel: giá / phân khúc (dòng tour) / điểm KH / thời gian.

Chạy trên VPS để paste output ra → thấy NGAY giá nào đúng, dòng tour parse đúng chưa.

CÁCH CHẠY (trên VPS, trong thư mục backend):
    python scripts/debug_vietravel_scrape.py
        → quét trang listing mặc định (du-lich-viet-nam.aspx), in N tour đầu.

    python scripts/debug_vietravel_scrape.py "<URL trang LISTING hoặc URL 1 TOUR>"
        → nếu là URL listing (.aspx): in các tour trong trang.
        → nếu là URL 1 tour (/chuong-trinh/...): chỉ phân tích đúng tour đó.

    python scripts/debug_vietravel_scrape.py "<URL>" 20
        → tham số thứ 2 = số tour tối đa in ra (mặc định 8).

Output mỗi tour:
  - ten_tour, dòng tour (raw + đã chọn), điểm KH, thời gian
  - TẤT CẢ salePrice tìm thấy (raw list) + giá sau heuristic _extract_prices + giải thích
  - CÁC FIELD GIÁ KHÁC trong JSON (priceFinal, priceOrigin, price, adultPrice, totalPrice...)
    để SO SÁNH xem field nào mới là giá tour ĐÚNG.
  - tourLineName / tourLineId raw.

KHÔNG ghi DB, KHÔNG ghi Sheet — chỉ đọc & in.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter

# Cho phép chạy từ bất kỳ đâu: thêm thư mục backend vào sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import requests  # noqa: E402

from scrapers.vietravel_scraper import (  # noqa: E402
    HEADERS,
    SOURCES,
    _LINKSHARE_RE,
    _PAGETITLE_RE,
    _TOURLINE_ID_RE,
    _TOURLINE_NAME_RE,
    _TOURLINE_BY_ID,
    _decode_json_str,
    _extract_departure,
    _extract_dong_tour,
    _extract_duration,
    _extract_prices,
    _extract_schedule,
    _fmt_price,
)

# Mọi field "có vẻ là giá" trong JSON nhúng → để so sánh với salePrice.
# Vietravel (Next.js) escape JSON: \"fieldName\":12345
_PRICE_FIELD_NAMES = [
    "salePrice",
    "price",
    "priceFinal",
    "priceOrigin",
    "originPrice",
    "originalPrice",
    "promotionPrice",
    "discountPrice",
    "adultPrice",
    "childPrice",
    "totalPrice",
    "depositPrice",
    "deposit",
    "priceFrom",
    "fromPrice",
    "minPrice",
    "maxPrice",
]


def _all_price_fields(chunk: str, max_len: int = 20000) -> dict[str, list[int]]:
    """Trích MỌI field giá để so sánh. Trả {fieldName: [values...]}."""
    sub = chunk[:max_len]
    out: dict[str, list[int]] = {}
    for name in _PRICE_FIELD_NAMES:
        pat = re.compile(r'\\"' + re.escape(name) + r'\\":(\d+)')
        vals = [int(x) for x in pat.findall(sub)]
        if vals:
            out[name] = vals
    return out


def _explain_extract_prices(chunk: str, max_len: int = 20000) -> str:
    """Tái hiện logic _extract_prices và GIẢI THÍCH đã lọc gì."""
    sub = chunk[:max_len]
    nums = [int(x) for x in re.findall(r'\\"salePrice\\":(\d+)', sub) if int(x) > 0]
    if not nums:
        return "salePrice: (không có) → gia = None"
    hi, lo = max(nums), min(nums)
    lines = [f"salePrice raw ({len(nums)} giá): {sorted(set(nums))}"]
    lines.append(f"  min={_fmt_price(lo)}  max={_fmt_price(hi)}  tỉ lệ max/min={hi / lo:.2f}x")
    if hi >= lo * 4:
        threshold = int(hi * 0.3)
        filtered = [n for n in nums if n >= threshold]
        kept = sorted(set(filtered))
        dropped = sorted(set(n for n in nums if n < threshold))
        lines.append(
            f"  ⚠ max/min >= 4x → KÍCH HOẠT heuristic lọc deposit "
            f"(ngưỡng = 30% max = {_fmt_price(threshold)})"
        )
        lines.append(f"     GIỮ (>= ngưỡng): {[_fmt_price(n) for n in kept]}")
        lines.append(f"     LOẠI (< ngưỡng, coi là cọc): {[_fmt_price(n) for n in dropped]}")
        result = min(filtered) if filtered else lo
        lines.append(f"  → gia = min(GIỮ) = {_fmt_price(result)}")
        if dropped:
            lines.append(
                "     ❗ KIỂM TRA: nếu các giá bị LOẠI thực ra là giá tour mùa thấp "
                "(không phải cọc) thì heuristic SAI → gia bị đội lên."
            )
    else:
        lines.append(f"  max/min < 4x → KHÔNG lọc, gia = min = {_fmt_price(lo)}")
    return "\n".join(lines)


def _split_cards(text: str) -> list[str]:
    marker = '\\"pageId\\":'
    if marker not in text:
        return []
    return text.split(marker)[1:]


def _analyze_card(chunk: str, idx: int) -> None:
    block = chunk[:40000]
    title_m = _PAGETITLE_RE.search(chunk)
    ten = _decode_json_str(title_m.group(1)) if title_m else "(không có pageTitle)"
    link_m = _LINKSHARE_RE.search(chunk)
    link = link_m.group(1) if link_m else "(không có linkShare)"

    print("=" * 78)
    print(f"[{idx}] {ten}")
    print(f"    link: {link}")
    print("-" * 78)

    # --- Phân khúc / dòng tour ---
    name_m = _TOURLINE_NAME_RE.search(chunk)
    id_m = _TOURLINE_ID_RE.search(chunk)
    raw_name = _decode_json_str(name_m.group(1)).strip() if name_m else ""
    raw_id = int(id_m.group(1)) if id_m else None
    all_names = sorted(set(_decode_json_str(v).strip() for v in _TOURLINE_NAME_RE.findall(chunk) if v.strip()))
    all_ids = sorted(set(int(x) for x in _TOURLINE_ID_RE.findall(chunk)))
    print("PHÂN KHÚC (dòng tour):")
    print(f"    tourLineName raw (đầu tiên): {raw_name!r}")
    print(f"    tourLineId raw (đầu tiên):   {raw_id}  → map: {_TOURLINE_BY_ID.get(raw_id, '(không map)') if raw_id else '-'}")
    if len(all_names) > 1 or len(all_ids) > 1:
        print(f"    ⚠ NHIỀU giá trị trong block (có thể lẫn MENU): names={all_names} ids={all_ids}")
    print(f"    => _extract_dong_tour() chọn: {_extract_dong_tour(chunk)!r}")

    # --- Giá ---
    print("GIÁ:")
    for line in _explain_extract_prices(chunk).split("\n"):
        print(f"    {line}")
    print(f"    => _extract_prices() trả: {_fmt_price(_extract_prices(block))!r}")
    other = _all_price_fields(chunk)
    print("    SO SÁNH các field giá khác trong JSON (kiểm field nào MỚI đúng):")
    if not other:
        print("        (không tìm thấy field giá nào)")
    for name, vals in other.items():
        uniq = sorted(set(vals))
        show = [_fmt_price(v) for v in uniq[:12]]
        more = "" if len(uniq) <= 12 else f" …(+{len(uniq) - 12})"
        print(f"        {name:<16}: {show}{more}")

    # --- Các field khác ---
    print("KHÁC:")
    print(f"    điểm KH (_extract_departure):  {_extract_departure(block)!r}")
    print(f"    thời gian (_extract_duration): {_extract_duration(block, chunk)!r}")
    sched = _extract_schedule(chunk)
    print(f"    lịch KH (_extract_schedule):   {sched[:80]!r}{'…' if len(sched) > 80 else ''}")


def _fetch(url: str) -> str:
    print(f"-> GET {url}")
    resp = requests.get(url, headers=HEADERS, timeout=90)
    print(f"   status={resp.status_code}  len={len(resp.text)}  encoding={resp.encoding}")
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def main() -> None:
    args = [a for a in sys.argv[1:]]
    url = args[0] if args else SOURCES[0]
    try:
        limit = int(args[1]) if len(args) > 1 else 8
    except ValueError:
        limit = 8

    text = _fetch(url)
    cards = _split_cards(text)

    if not cards:
        print("\n❌ KHÔNG thấy marker pageId trong trang.")
        print("   → site có thể chặn bot / đổi cấu trúc / URL không phải trang có data tour.")
        # Nếu là URL 1 tour detail: vẫn thử trích tourLineId + salePrice thô để chẩn đoán.
        print("\n   Thử trích THÔ từ toàn trang (cho URL trang chi tiết 1 tour):")
        sale = sorted(set(int(x) for x in re.findall(r'\\"salePrice\\":(\d+)', text) if int(x) > 0))
        print(f"     salePrice toàn trang: {[_fmt_price(v) for v in sale]}")
        tid = _TOURLINE_ID_RE.search(text)
        print(f"     tourLineId: {tid.group(1) if tid else None} "
              f"→ {_TOURLINE_BY_ID.get(int(tid.group(1)), '(không map)') if tid else '-'}")
        for name in _PRICE_FIELD_NAMES:
            pat = re.compile(r'\\"' + re.escape(name) + r'\\":(\d+)')
            vals = sorted(set(int(x) for x in pat.findall(text)))
            if vals:
                print(f"     {name}: {[_fmt_price(v) for v in vals[:12]]}")
        return

    print(f"\n✅ Tìm thấy {len(cards)} card. In tối đa {limit} card có linkShare:\n")
    shown = 0
    for chunk in cards:
        if not _LINKSHARE_RE.search(chunk):
            continue
        shown += 1
        _analyze_card(chunk, shown)
        if shown >= limit:
            break
    print("=" * 78)
    print(f"Đã in {shown}/{len(cards)} card.")
    print(
        "\nĐỌC KẾT QUẢ:\n"
        "  - Nếu 'gia' khác xa với giá tour thật trên web → xem dòng 'SO SÁNH field giá khác':\n"
        "    field nào khớp giá web mới là field ĐÚNG (báo lại để đổi salePrice -> field đó).\n"
        "  - Nếu heuristic 'LOẠI (coi là cọc)' đang bỏ NHẦM giá mùa thấp → báo lại để bỏ/đổi ngưỡng.\n"
        "  - Nếu phân khúc (dòng tour) sai → xem tourLineName/tourLineId raw có khớp tier web không."
    )


if __name__ == "__main__":
    main()
