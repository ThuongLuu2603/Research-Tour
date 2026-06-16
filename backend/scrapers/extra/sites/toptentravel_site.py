"""Extra scraper: Top Ten Travel (toptentravel.com.vn).

2 trang danh sách (server-render HTML, ~15 tour/trang, phân trang ?pagenumber=N):
  - https://toptentravel.com.vn/tour-nuoc-ngoai  (nước ngoài)
  - https://toptentravel.com.vn/tour-trong-nuoc   (trong nước)

Mỗi card `<div class="tour-item">`: h3>a (tên+link), .price, "Mã tour", "Nơi Khởi
hành", và <select> chứa các option NGÀY KH dd/mm/yyyy (hoặc "Liên hệ" = không có).

CLOUDFLARE: site dùng Turnstile có thể chặn IP datacenter (VPS). CHỈ fetch trực
tiếp (KHÔNG dùng ScraperAPI/proxy theo yêu cầu). IP nhà mạng qua thẳng được; nếu
VPS bị chặn → trả rỗng + log cảnh báo. KHÔNG bịa lịch trình → lich_trinh="".
"""
from __future__ import annotations

import logging
import re
from typing import Callable

import pandas as pd
import requests

from scrapers.extra.registry import ExtraScraper, register
from scrapers.extra.sites.example_site import STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_COMPANY = "Top Ten Travel"
_LISTINGS = [
    "https://toptentravel.com.vn/tour-nuoc-ngoai",
    "https://toptentravel.com.vn/tour-trong-nuoc",
]
_MAX_PAGES = 40          # cap an toàn / 1 listing
_TIMEOUT = 40
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}
_CF_MARKERS = ("cf-chl", "turnstile", "just a moment", "checking your browser", "challenge-platform")


def _first(pat: str, s: str, default: str = "") -> str:
    m = re.search(pat, s, re.S | re.I)
    return m.group(1).strip() if m else default


def _fmt_thoi_gian(name: str) -> str:
    """'...9N8D' / '4N3Đ' → '9N8Đ'. Không thấy → ''."""
    m = re.search(r"(\d{1,2})\s*[Nn]\s*(\d{1,2})\s*[ĐđDd]", name or "")
    return f"{int(m.group(1))}N{int(m.group(2))}Đ" if m else ""


def _fetch(url: str, session: requests.Session) -> str:
    """GET trực tiếp. Bị Cloudflare/403/trang rỗng → trả '' + log (KHÔNG dùng proxy)."""
    try:
        r = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        html = r.text
        low = html.lower()
        blocked = (r.status_code != 200) or any(m in low for m in _CF_MARKERS) or len(html) < 3000
        if not blocked:
            return html
        logger.warning(
            "TopTen: bị chặn (status=%s, len=%s, cloudflare?). IP này (VPS?) không qua "
            "được — cần chạy từ IP nhà mạng. KHÔNG fallback proxy theo cấu hình.",
            r.status_code, len(html),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("TopTen: fetch lỗi: %s", e)
    return ""


def _parse_cards(html: str) -> list[dict]:
    rows: list[dict] = []
    blocks = re.split(r'<div class="tour-item', html)[1:]
    for b in blocks:
        link = _first(r'href="(https://toptentravel\.com\.vn/[^"]+)"', b)
        name = _first(r"<h3[^>]*>\s*<a[^>]*>([^<]+)</a>", b) or _first(r'title="([^"]+)"', b)
        if not name or not link:
            continue
        price = _first(r'class="price">([^<]+)<', b)
        price = re.sub(r"[^\d.]", "", price)  # '41.900.000 VND' → '41.900.000'
        ma = _first(r"Mã tour:\s*<span>([^<]+)</span>", b)
        dep = _first(r"Khởi hành:\s*<span>([^<]+)</span>", b)
        dates = re.findall(r'<option value="[^"]*">\s*(\d{1,2}/\d{1,2}/\d{4})', b)
        rows.append({
            "cong_ty": _COMPANY,
            "thi_truong": "",
            "tuyen_tour": "",
            "ten_tour": name,
            "lich_trinh": "",
            "diem_kh": dep,
            "thoi_gian": _fmt_thoi_gian(name),
            "gia": price,
            "lich_kh": ", ".join(dict.fromkeys(dates)),
            "link_url": link,
            "ma_tour": ma,
            "khach_san": "",
            "hang_khong": "",
        })
    return rows


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    session = requests.Session()
    all_rows: list[dict] = []
    seen_links: set[str] = set()

    for li, base in enumerate(_LISTINGS):
        for page in range(1, _MAX_PAGES + 1):
            url = base if page == 1 else f"{base}?pagenumber={page}"
            if progress:
                pct = 5 + int(85 * (li * _MAX_PAGES + page) / (len(_LISTINGS) * _MAX_PAGES))
                progress(min(pct, 92), f"Top Ten: {base.rsplit('/', 1)[-1]} trang {page} ({len(all_rows)} tour)")
            html = _fetch(url, session)
            if not html:
                break
            cards = _parse_cards(html)
            if not cards:
                break  # hết trang
            new = 0
            for c in cards:
                if c["link_url"] in seen_links:
                    continue
                seen_links.add(c["link_url"])
                all_rows.append(c)
                new += 1
            if new == 0:
                break  # trang lặp lại tour cũ → dừng

    # Phân loại thị trường/tuyến từ tên (như các nguồn khác).
    try:
        from classification import classify_route_fields
        for r in all_rows:
            mk, rt = classify_route_fields(r["ten_tour"], "")
            r["thi_truong"], r["tuyen_tour"] = mk, rt
    except Exception:  # noqa: BLE001
        pass

    df = pd.DataFrame(all_rows, columns=STANDARD_COLUMNS)
    if progress:
        progress(100, f"Top Ten xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="toptentravel",
    name="Top Ten Travel",
    scrape=scrape,
))
