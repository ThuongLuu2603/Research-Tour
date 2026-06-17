"""Extra scraper: Đất Việt Tour (datviettour.com.vn).

Listing load qua AJAX (Laravel) — KHÔNG có trong HTML tĩnh:
  POST https://datviettour.com.vn/tours/loadtours  (x-www-form-urlencoded, XHR)
  cần: _token (CSRF, từ meta csrf-token) + cookie session + X-Requested-With.
  body: page, parent_menu, total_load=0, filter[category_id], filter[title_page],
        filter[key_search]='', filter[slug]='', filter[departure_id]=''
  -> JSON {html: "<card...>", total: N, page_size: 12}.

2 danh mục: du-lich-nuoc-ngoai (category_id=17) + du-lich-trong-nuoc (category_id='').
Card: tour-title / tour-price / fa-calendar(ngày) / fa-clock-o(thời gian) /
fa-plane|bus(phương tiện) / fa-building(khách sạn=sao) / "KH từ:"(điểm KH).

Card chỉ hiện 1 NGÀY KH gần nhất + 1 giá (giá/lịch đầy đủ ở trang chi tiết — chưa
lấy để giữ nhanh). KHÔNG bịa lịch trình. CHỈ fetch trực tiếp (không proxy).
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd
import requests

from scrapers.extra.registry import ExtraScraper, register
from scrapers.extra.sites.example_site import STANDARD_COLUMNS

logger = logging.getLogger(__name__)

_COMPANY = "Đất Việt Tour"
_BASE = "https://datviettour.com.vn"
_LOAD_URL = f"{_BASE}/tours/loadtours"
# (parent_menu, category_id, title_page). category_id='' = KHÔNG lọc → trả TẤT CẢ
# tour (cả trong nước + nước ngoài, ~180). 1 call là đủ toàn bộ catalog.
_CATEGORIES = [
    ("du-lich-trong-nuoc", "", "Tour Trong Nước"),
]
_PAGE_SIZE = 12
_MAX_PAGES = 60
_TIMEOUT = 45
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def _first(pat: str, s: str, default: str = "") -> str:
    m = re.search(pat, s, re.S | re.I)
    return m.group(1).strip() if m else default


def _norm_duration(s: str) -> str:
    m = re.search(r"(\d+)\s*ngày\s*(\d+)\s*đêm", s or "", re.I)
    if m:
        return f"{m.group(1)}N{m.group(2)}Đ"
    m = re.search(r"(\d+)\s*ngày", s or "", re.I)
    return f"{m.group(1)}N" if m else ""


def _csrf_session() -> tuple[requests.Session, str]:
    """GET homepage → session (cookie) + CSRF token (meta csrf-token)."""
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "vi"})
    html = s.get(_BASE + "/", timeout=_TIMEOUT).text
    token = _first(r'name="csrf-token"\s+content="([^"]+)"', html)
    return s, token


def _parse_cards(html: str) -> list[dict]:
    rows: list[dict] = []
    for blk in re.split(r'class="[^"]*item-tour product-one', html)[1:]:
        link = _first(r'href="(/[^"#]+-\d+|/[a-z0-9-]+)"', blk)
        name = _first(r'tour-title">\s*([^<]+?)\s*<', blk)
        if not name or not link:
            continue
        if link.startswith("/"):
            link = _BASE + link
        dep = _first(r'KH từ:\s*([^<]+?)\s*<', blk)
        dur = _norm_duration(_first(r'fa-clock-o"></i>\s*([^<]+?)\s*</div>', blk))
        date = _first(r'fa-calendar"></i>\s*(\d{1,2}/\d{1,2}/\d{4})', blk)
        trans = _first(r'fa-(?:plane|bus|train|car|ship|subway)"></i>\s*([^<]+?)\s*</div>', blk)
        hotel = _first(r'fa-building"></i>\s*([^<]+?)\s*</div>', blk)
        price_raw = _first(r'tour-price">\s*([\d.,]+)', blk)
        gia = re.sub(r"\D", "", price_raw)
        gia = f"{int(gia):,}".replace(",", ".") if gia else ""
        ma = _first(r"-(\d+)$", link)
        rows.append({
            "cong_ty": _COMPANY,
            "thi_truong": "",
            "tuyen_tour": "",
            "ten_tour": name,
            "lich_trinh": "",
            "diem_kh": dep,
            "thoi_gian": dur,
            "gia": gia,
            "lich_kh": date,
            "link_url": link,
            "ma_tour": ma,
            "hang_khong": trans,
            "khach_san": hotel,
        })
    return rows


def _fetch_detail_schedule(url: str) -> tuple[dict[int, list[str]], dict[int, str]]:
    """Trang chi tiết có bảng lịch KH: <tr><td>STT</td><td>ngày</td><td>khách sạn</td>
    <td>giá đ</td>. Trả (groups: giá→[ngày dd/mm/yyyy], hotels: giá→khách sạn).
    Lỗi/không có bảng → ({}, {})."""
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "vi"}, timeout=_TIMEOUT)
        html = r.text
    except Exception as e:  # noqa: BLE001
        logger.warning("Đất Việt detail %s lỗi: %s", url, e)
        return {}, {}
    groups: dict[int, list[str]] = {}
    hotels: dict[int, str] = {}
    for m in re.finditer(
        r"<td>\s*(\d{1,2}/\d{1,2}/\d{4})\s*</td>\s*<td>([\s\S]*?)</td>\s*"
        r'<td[^>]*>\s*([\d.,]{6,})\s*[đ₫]',
        html,
    ):
        try:
            dd, mm, yy = m.group(1).split("/")
            date = f"{int(dd):02d}/{int(mm):02d}/{yy}"
        except ValueError:
            continue
        hotel = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
        price = int(re.sub(r"\D", "", m.group(3)) or 0)
        if price <= 0:
            continue
        groups.setdefault(price, [])
        if date not in groups[price]:
            groups[price].append(date)
        hotels.setdefault(price, hotel)
    return groups, hotels


def _rows_with_schedule(base: dict) -> list[dict]:
    """1 tour → nhiều dòng theo giá (ngày cùng giá gộp, khác giá tách). Không lấy được
    bảng lịch → giữ 1 dòng card (1 ngày + 1 giá gần nhất)."""
    groups, hotels = _fetch_detail_schedule(base["link_url"])
    if not groups:
        return [base]
    out: list[dict] = []
    for price in sorted(groups, key=lambda p: min(groups[p])):
        r = dict(base)
        r["gia"] = f"{price:,}".replace(",", ".")
        r["lich_kh"] = ", ".join(sorted(groups[price], key=lambda d: (d[6:], d[3:5], d[:2])))
        if hotels.get(price):
            r["khach_san"] = hotels[price]
        out.append(r)
    return out


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    try:
        session, token = _csrf_session()
    except Exception as e:  # noqa: BLE001
        logger.warning("Đất Việt: lấy CSRF/cookie lỗi: %s", e)
        return pd.DataFrame(columns=STANDARD_COLUMNS)
    if not token:
        logger.warning("Đất Việt: không lấy được CSRF token")
        return pd.DataFrame(columns=STANDARD_COLUMNS)

    ajax_headers = {
        "User-Agent": _UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "vi",
        "X-CSRF-TOKEN": token,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": _BASE,
    }
    all_rows: list[dict] = []
    seen: set[str] = set()

    for ci, (parent_menu, cat_id, title_page) in enumerate(_CATEGORIES):
        ajax_headers["Referer"] = f"{_BASE}/{parent_menu}"
        total = None
        loaded = 0  # offset luỹ tiến — server dùng total_load để bỏ qua N tour đã load.
        for page in range(1, _MAX_PAGES + 1):
            body = {
                "_token": token,
                "page": str(page),
                "parent_menu": parent_menu,
                "total_load": str(loaded),
                "filter[key_search]": "",
                "filter[slug]": "",
                "filter[category_id]": cat_id,
                "filter[title_page]": title_page,
                "filter[departure_id]": "",
            }
            try:
                r = session.post(_LOAD_URL, data=body, headers=ajax_headers, timeout=_TIMEOUT)
                data = r.json()
            except Exception as e:  # noqa: BLE001
                logger.warning("Đất Việt: loadtours %s page %s lỗi: %s", parent_menu, page, e)
                break
            if total is None:
                total = int(data.get("total") or 0)
            html = data.get("html") or ""
            n_cards = html.count("item-tour product-one")  # số card server trả lượt này
            if n_cards == 0:
                break
            for c in _parse_cards(html):
                if c["link_url"] in seen:
                    continue
                seen.add(c["link_url"])
                all_rows.append(c)
            loaded += n_cards
            if progress:
                pct = 5 + int(85 * (ci + loaded / max(total, 1)) / len(_CATEGORIES))
                progress(min(pct, 92), f"Đất Việt: {title_page} ({len(all_rows)}/{total or '?'})")
            if total and loaded >= total:
                break

    # Phase 2: vào trang CHI TIẾT (song song) lấy ĐỦ lịch KH + TÁCH GIÁ (ngày cùng giá
    # gộp 1 dòng, khác giá tách dòng). 8 luồng (nhẹ, tránh site throttle).
    split_rows: list[dict] = []
    if all_rows:
        if progress:
            progress(94, f"Đất Việt: lấy lịch/giá chi tiết {len(all_rows)} tour…")
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_rows_with_schedule, b): b for b in all_rows}
            for fut in as_completed(futs):
                try:
                    split_rows.extend(fut.result())
                except Exception:  # noqa: BLE001
                    split_rows.append(futs[fut])
    else:
        split_rows = all_rows
    all_rows = split_rows

    try:
        from classification import classify_route_fields
        for r in all_rows:
            r["thi_truong"], r["tuyen_tour"] = classify_route_fields(r["ten_tour"], "")
    except Exception:  # noqa: BLE001
        pass

    df = pd.DataFrame(all_rows, columns=STANDARD_COLUMNS)
    if progress:
        progress(100, f"Đất Việt xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="datviettour",
    name="Đất Việt Tour",
    scrape=scrape,
))
