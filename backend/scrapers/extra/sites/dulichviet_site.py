"""Extra scraper: Du Lịch Việt (dulichviet.com.vn).

3 trang danh sách (HTML server-render, card `.mda-box-item`):
  - /du-lich-trong-nuoc?TourLocalSearchStart=&StatDay=
  - /du-lich-chau-a?TourLocalSearchStart=&StatDay=
  - /du-lich-nuoc-ngoai?TourLocalSearchStart=&StatDay=

Mỗi card: tên/link (`a.mda-box-name`), mã tour / điểm KH / thời gian / phương tiện
(`.item-brief-detail`), giá (`.price-min h4`), lịch KH (`.list-startdate-brief .day-tour a`).

Cần User-Agent trình duyệt đầy đủ (thiếu → 403). KHÔNG bịa lịch trình.
"""
from __future__ import annotations

import logging
import re
from typing import Callable
from urllib.parse import urljoin

import pandas as pd
import requests

from scrapers.extra.registry import ExtraScraper, register
from scrapers.extra.sites.example_site import STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_COMPANY = "Du Lịch Việt"
_BASE = "https://dulichviet.com.vn"
_LISTINGS: list[tuple[str, str]] = [
    ("Trong nước", f"{_BASE}/du-lich-trong-nuoc?TourLocalSearchStart=&StatDay="),
    ("Châu Á", f"{_BASE}/du-lich-chau-a?TourLocalSearchStart=&StatDay="),
    ("Nước ngoài", f"{_BASE}/du-lich-nuoc-ngoai?TourLocalSearchStart=&StatDay="),
]
_TIMEOUT = 45
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


def _first(pat: str, s: str, default: str = "") -> str:
    m = re.search(pat, s, re.S | re.I)
    return m.group(1).strip() if m else default


def _abs_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    return urljoin(_BASE + "/", href)


def _format_gia(price_raw: str) -> str:
    digits = re.sub(r"\D", "", price_raw or "")
    if not digits:
        return ""
    val = int(digits)
    return f"{val:,}".replace(",", ".") if val >= 100_000 else ""


def _brief(card: str, label: str) -> str:
    for blk in re.findall(r'class="item-brief-detail"[^>]*>(.*?)</div>', card, re.S | re.I):
        plain = re.sub(r"<[^>]+>", " ", blk)
        plain = re.sub(r"\s+", " ", plain).strip()
        if label.lower() in plain.lower():
            return _first(r"<b[^>]*>\s*([^<]+?)\s*</b>", blk)
    return ""


def _parse_cards(html: str, *, market: str) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()

    for card in re.split(r'class="[^"]*mda-box-item', html)[1:]:
        link = _abs_url(_first(r'class="mda-box-name[^"]*"\s+href="([^"]+)"', card))
        title = _first(r'class="mda-box-name[^"]*"[^>]*>\s*([^<]+?)\s*<', card)
        if not link or not title:
            continue
        key = link.split("?")[0].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)

        price_raw = _first(
            r'class="price-min"[^>]*>.*?<h4[^>]*>\s*([^<]+?)\s*</h4>',
            card,
        )
        if not price_raw:
            price_raw = _first(
                r'class="list-price-brief"[^>]*>.*?([\d][\d.,]{5,})\s*(?:đ|&#273;|&nbsp;đ)',
                card,
            )
        dates = re.findall(
            r'class="day-tour"[^>]*>\s*<a[^>]*>\s*(\d{1,2}/\d{1,2})\s*</a>',
            card,
        )

        rows.append({
            "cong_ty": _COMPANY,
            "thi_truong": market,
            "tuyen_tour": "",
            "ten_tour": title,
            "lich_trinh": "",
            "diem_kh": _brief(card, "Khởi hành"),
            "thoi_gian": _brief(card, "Thời gian"),
            "gia": _format_gia(price_raw),
            "lich_kh": ", ".join(dates),
            "link_url": link,
            "ma_tour": _brief(card, "Mã tour"),
            "hang_khong": _brief(card, "Phương tiện"),
            "khach_san": "",
        })
    return rows


def _fetch(url: str, session: requests.Session) -> str:
    try:
        r = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if r.status_code == 200 and len(r.text) > 5000 and "mda-box-item" in r.text:
            return r.text
        logger.warning(
            "Du Lịch Việt: fetch lỗi/chặn %s (status=%s len=%s)",
            url, r.status_code, len(r.text),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Du Lịch Việt: fetch exception %s: %s", url, e)
    return ""


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    session = requests.Session()
    all_rows: list[dict] = []
    seen_links: set[str] = set()

    for i, (market, url) in enumerate(_LISTINGS):
        if progress:
            pct = 5 + int(85 * i / len(_LISTINGS))
            progress(pct, f"Du Lịch Việt: {market}…")
        html = _fetch(url, session)
        if not html:
            continue
        for row in _parse_cards(html, market=market):
            key = row["link_url"].split("?")[0].rstrip("/").lower()
            if key in seen_links:
                continue
            seen_links.add(key)
            all_rows.append(row)

    try:
        from classification import classify_route_fields
        for r in all_rows:
            _, tuyen = classify_route_fields(r["ten_tour"], "")
            if tuyen:
                r["tuyen_tour"] = tuyen
    except Exception:  # noqa: BLE001
        pass

    df = pd.DataFrame(all_rows, columns=STANDARD_COLUMNS)
    if progress:
        progress(100, f"Du Lịch Việt xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="dulichviet",
    name="Du Lịch Việt",
    scrape=scrape,
))
