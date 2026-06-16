"""Extra scraper: Hải Đăng Travel (haidangtravel.com).

2 trang danh sách (server-render HTML Tailwind, phân trang ?page=N):
  - https://haidangtravel.com/tour-trong-nuoc?q=&category=
  - https://haidangtravel.com/tour-nuoc-ngoai

Card (<article>): tên (h2/h3), link /chuong-trinh/{slug}, "X ngày Y đêm", giá
("Giá từ": gạch ngang giá gốc + giá sale đậm). Trang chi tiết có JSON-LD với
PropertyValue: "Điểm khởi hành", "Phương tiện", + mô tả "Khởi hành <lịch>".

NGÀY KH: Hải Đăng dùng LỊCH TUẦN ("Thứ 5 hàng tuần"), KHÔNG có ngày dd/mm cụ thể →
lich_kh = chuỗi lịch (user cấu hình rule 'Định dạng Ngày KH' để tính tần suất).
1 GIÁ/tour (không có giá theo ngày) → không tách dòng giá.

CLOUDFLARE: server=cloudflare nhưng (17/6) KHÔNG challenge từ IP nhà mạng. CHỈ fetch
trực tiếp (KHÔNG proxy/ScraperAPI). VPS bị chặn → trả rỗng. KHÔNG bịa lịch trình.
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

_COMPANY = "Hải Đăng Travel"
_LISTINGS = [
    "https://haidangtravel.com/tour-trong-nuoc?q=&category=",
    "https://haidangtravel.com/tour-nuoc-ngoai",
]
_MAX_PAGES = 30
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


def _norm_duration(s: str) -> str:
    """'4 ngày 3 đêm' → '4N3Đ'; '2 ngày' → '2N'. Không thấy → ''."""
    m = re.search(r"(\d+)\s*ngày\s*(\d+)\s*đêm", s or "", re.I)
    if m:
        return f"{m.group(1)}N{m.group(2)}Đ"
    m = re.search(r"(\d+)\s*ngày", s or "", re.I)
    return f"{m.group(1)}N" if m else ""


def _fetch(url: str, session: requests.Session) -> str:
    """GET trực tiếp. Bị Cloudflare/403/trang rỗng → '' + log (KHÔNG proxy)."""
    try:
        r = session.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        html = r.text
        low = html.lower()
        blocked = (r.status_code != 200) or any(m in low for m in _CF_MARKERS) or len(html) < 3000
        if not blocked:
            return html
        logger.warning("HaiDang: bị chặn (status=%s len=%s) — IP này (VPS?) không qua "
                       "Cloudflare; KHÔNG fallback proxy.", r.status_code, len(html))
    except Exception as e:  # noqa: BLE001
        logger.warning("HaiDang: fetch lỗi: %s", e)
    return ""


def _ld_prop(html: str, label: str) -> str:
    """Lấy value của PropertyValue trong JSON-LD: {"name":"<label>","value":"<v>"}."""
    return _first(r'"name"\s*:\s*"' + re.escape(label) + r'"\s*,\s*"value"\s*:\s*"([^"]+)"', html)


def _parse_cards(html: str) -> list[dict]:
    rows: list[dict] = []
    for a in re.split(r"<article", html)[1:]:
        if "chuong-trinh" not in a:
            continue
        link = _first(r'href="(https?://haidangtravel\.com/chuong-trinh/[^"]+)"', a)
        name = _first(r"<(?:h2|h3)[^>]*>\s*(?:<a[^>]*>)?\s*([^<]+)", a)
        if not link or not name:
            continue
        dur = _norm_duration(_first(r">\s*(\d+\s*ngày\s*\d+\s*đêm)\s*<", a))
        # Giá: card có giá gốc (gạch ngang) + giá sale → lấy giá NHỎ NHẤT (sale = "Giá từ").
        nums = [int(re.sub(r"\D", "", p)) for p in re.findall(r"([\d][\d.]{5,})\s*đ", a)]
        nums = [n for n in nums if n > 0]
        gia = f"{min(nums):,}".replace(",", ".") if nums else ""
        rows.append({
            "cong_ty": _COMPANY,
            "thi_truong": "",
            "tuyen_tour": "",
            "ten_tour": name,
            "lich_trinh": "",
            "diem_kh": "",
            "thoi_gian": dur,
            "gia": gia,
            "lich_kh": "",
            "link_url": link,
            "ma_tour": "",
            "hang_khong": "",
            "khach_san": "",
        })
    return rows


def _fetch_detail(url: str) -> tuple[str, str, str, str]:
    """Trang chi tiết → (điểm KH, phương tiện, thời gian, lịch KH tuần). Lỗi → ('','','','')."""
    html = _fetch(url, requests.Session())
    if not html:
        return "", "", "", ""
    dep = _ld_prop(html, "Điểm khởi hành")
    trans = _ld_prop(html, "Phương tiện")
    dur = _norm_duration(_ld_prop(html, "Thời lượng") or _first(r"Thời gian:\s*([^<\n]{2,20})", html))
    # Lịch tuần trong text: "Khởi hành [tối] Thứ 5 hàng tuần" / "khởi hành hàng ngày".
    # Cho phép từ chen (tối/sáng…) giữa "Khởi hành" và thứ; chặn nhiễu "khởi hành trước 10 ngày".
    sched = _first(
        r'[Kk]hởi h[àa]nh[^.<"]{0,18}?'
        r'(Thứ\s*[2-7][^.<"]{0,18}?hàng\s*tuần|Chủ\s*nhật[^.<"]{0,12}?hàng\s*tuần|h[àă]ng\s*ngày)',
        html,
    )
    sched = re.sub(r"\s+", " ", sched).strip()
    return dep, trans, dur, sched


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    session = requests.Session()
    all_rows: list[dict] = []
    seen: set[str] = set()

    for li, base in enumerate(_LISTINGS):
        sep = "&" if "?" in base else "?"
        for page in range(1, _MAX_PAGES + 1):
            url = base if page == 1 else f"{base}{sep}page={page}"
            if progress:
                pct = 5 + int(45 * (li * _MAX_PAGES + page) / (len(_LISTINGS) * _MAX_PAGES))
                progress(min(pct, 50), f"Hải Đăng: {base.rsplit('/', 1)[-1][:20]} trang {page} ({len(all_rows)})")
            html = _fetch(url, session)
            if not html:
                break
            cards = _parse_cards(html)
            new = 0
            for c in cards:
                if c["link_url"] in seen:
                    continue
                seen.add(c["link_url"])
                all_rows.append(c)
                new += 1
            if new == 0:
                break

    # Chi tiết (SONG SONG): điểm KH + phương tiện(→hàng không) + lịch tuần + số ngày.
    if all_rows:
        if progress:
            progress(60, f"Hải Đăng: chi tiết {len(all_rows)} tour (song song)…")
        with ThreadPoolExecutor(max_workers=16) as ex:
            futs = {ex.submit(_fetch_detail, r["link_url"]): r for r in all_rows}
            for fut in as_completed(futs):
                r = futs[fut]
                try:
                    dep, trans, dur, sched = fut.result()
                except Exception:  # noqa: BLE001
                    dep, trans, dur, sched = "", "", "", ""
                if dep:
                    r["diem_kh"] = dep
                if trans:
                    r["hang_khong"] = trans
                if dur and not r["thoi_gian"]:
                    r["thoi_gian"] = dur
                if sched:
                    r["lich_kh"] = sched

    try:
        from classification import classify_route_fields
        for r in all_rows:
            r["thi_truong"], r["tuyen_tour"] = classify_route_fields(r["ten_tour"], "")
    except Exception:  # noqa: BLE001
        pass

    df = pd.DataFrame(all_rows, columns=STANDARD_COLUMNS)
    if progress:
        progress(100, f"Hải Đăng xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="haidangtravel",
    name="Hải Đăng Travel",
    scrape=scrape,
))
