"""Scrape vietnam.travel/event + visitvietnams.com — Sự kiện & Lễ hội VN.

3 chế độ fetch (ưu tiên theo thứ tự):

  1. GOOGLE APPS SCRIPT PROXY (recommend — luôn work)
     User deploy file _workspace/google_apps_script_festival_proxy.gs làm
     Web App. Set env var FESTIVAL_PROXY_URL=https://script.google.com/macros/s/.../exec
     Backend fetch JSON từ URL này → instant data, không cần parse HTML.

  2. JINA READER PROXY (fallback)
     Free 1M token/tháng. r.jina.ai/{url} trả markdown của trang.
     Backend parse markdown để extract events.

  3. PUBLIC CORS PROXY chain (last resort)
     allorigins.win, codetabs.com, ... — bất ổn (520, 403).

Lý do cần proxy: Render outbound → vietnam.travel/visitvietnams bị
Cloudflare/WAF block → ConnectTimeout. Google Apps Script chạy trên
Google IP whitelist nên fetch OK.

Tần suất: weekly cron. Crawl: 24 list page VT + 15 page VV qua proxy.
"""
import os
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://vietnam.travel"
EVENT_LIST_URL = f"{BASE_URL}/event"
DETAIL_PATH_PREFIX = "/things-to-do/festival-event/"

# Secondary source: visitvietnams.com — pagination ?page=N
# Robots.txt cho /events OK. Detail URL pattern guess: /en/events/{slug}
VV_BASE_URL = "https://visitvietnams.com"
VV_EVENT_LIST_URL = f"{VV_BASE_URL}/en/events"
# Confirmed pattern qua Jina probe: chỉ /en/events/{slug}, không có /en/event/ hay /en/festival/.
VV_DETAIL_PATH_PREFIXES = ("/en/events/",)
VV_MAX_PAGES = 15  # 15 page × 20 event = 300 event max

# Render free tier outbound → vietnam.travel có thể bị throttle hoặc IP range
# bị Cloudflare flag. Public CORS proxies như allorigins.win đôi khi cũng down
# (520 overload, 403). Strategy: fail-fast direct (5s) → thử 4 proxy provider
# khác nhau (mỗi proxy 10s timeout). Total worst-case ~45s/page thay vì 60s+.
#
# Lưu ý: bằng cách probe (WebFetch test), thấy allorigins đôi khi 520; corsproxy
# đôi khi 403. Vì vậy NHIỀU candidate cần thiết, mỗi cái fail-fast.
DIRECT_TIMEOUT_SEC = 5.0   # ConnectTimeout < 5s = chắc chắn không reach được
PROXY_TIMEOUT_SEC = 15.0   # Proxy edge thường nhanh hơn, đặt 15s overhead
RATE_LIMIT_SEC = 1.0       # Giảm rate limit vì có nhiều proxy candidates

# Proxy chain — sort theo độ tin cậy. r.jina.ai là Jina AI Reader (free 1M
# token/tháng, KHÔNG bị Cloudflare block vì là AI research tool nổi tiếng).
# Đặt đầu tiên vì stable hơn public CORS proxies hỗn loạn.
PROXY_PROVIDERS = [
    # (name, build_fn) — build_fn(target_url) -> proxy URL
    ("jina-reader",    lambda u: f"https://r.jina.ai/{u}"),  # path-prefix style
    ("allorigins-raw", lambda u: f"https://api.allorigins.win/raw?url={_url_encode(u)}"),
    ("codetabs",       lambda u: f"https://api.codetabs.com/v1/proxy?quest={_url_encode(u)}"),
    ("corsproxy.io",   lambda u: f"https://corsproxy.io/?{_url_encode(u)}"),
    ("allorigins-get", lambda u: f"https://api.allorigins.win/get?url={_url_encode(u)}"),  # JSON wrapper
    ("thingproxy",     lambda u: f"https://thingproxy.freeboard.io/fetch/{u}"),
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _url_encode(u: str) -> str:
    from urllib.parse import quote
    return quote(u, safe="")

# Tháng tiếng Anh → số (vietnam.travel dùng query ?month=jun&year=2026)
_MONTH_SLUG = [
    "jan", "feb", "mar", "apr", "may", "jun",
    "jul", "aug", "sep", "oct", "nov", "dec",
]

# Map prefix tỉnh → vùng (Phase 1 hardcode; Phase 2 sẽ join provinces table)
_REGION_BY_PROVINCE_KEYWORD: dict[str, str] = {
    # Bắc
    "hà nội": "bac", "ha noi": "bac", "hanoi": "bac",
    "hải phòng": "bac", "quảng ninh": "bac", "lào cai": "bac", "sapa": "bac",
    "ninh bình": "bac", "hà giang": "bac", "thái nguyên": "bac",
    "bắc ninh": "bac", "phú thọ": "bac", "yên bái": "bac",
    "điện biên": "bac", "lạng sơn": "bac", "tuyên quang": "bac",
    # Trung
    "huế": "trung", "thừa thiên": "trung", "đà nẵng": "trung", "da nang": "trung",
    "hội an": "trung", "hoi an": "trung", "quảng nam": "trung",
    "quảng bình": "trung", "quảng trị": "trung", "khánh hòa": "trung",
    "nha trang": "trung", "phú yên": "trung", "bình định": "trung",
    "ninh thuận": "trung", "bình thuận": "trung", "phan thiết": "trung",
    "đà lạt": "trung", "lâm đồng": "trung", "kon tum": "trung",
    "gia lai": "trung", "đắk lắk": "trung", "buôn ma thuột": "trung",
    # Nam
    "hồ chí minh": "nam", "ho chi minh": "nam", "sài gòn": "nam", "saigon": "nam",
    "tp.hcm": "nam", "tphcm": "nam", "hcm": "nam",
    "cần thơ": "nam", "vũng tàu": "nam", "bà rịa": "nam",
    "đồng nai": "nam", "bình dương": "nam", "long an": "nam",
    "tiền giang": "nam", "bến tre": "nam", "vĩnh long": "nam",
    "an giang": "nam", "kiên giang": "nam", "phú quốc": "nam",
    "cà mau": "nam", "sóc trăng": "nam", "trà vinh": "nam",
    "đồng tháp": "nam", "hậu giang": "nam", "bạc liêu": "nam",
}

# Map từ khóa → category
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "religious": ["chùa", "đền", "phật", "lễ phật", "lễ chùa", "vu lan", "phật đản", "tâm linh"],
    "cultural":  ["lễ hội", "truyền thống", "văn hóa", "dân gian", "cổ truyền", "hội"],
    "music":     ["âm nhạc", "festival music", "concert", "âm thanh"],
    "food":      ["ẩm thực", "food", "trà", "cà phê", "ngon"],
    "sport":     ["thể thao", "marathon", "đua", "bóng", "ironman"],
}


def _slugify(s: str) -> str:
    """URL slug an toàn: lower, ascii, dash."""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s)
    return s[:240] or "untitled"


def _compute_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _classify_region(location_text: str) -> str:
    if not location_text:
        return ""
    lt = location_text.lower()
    for kw, region in _REGION_BY_PROVINCE_KEYWORD.items():
        if kw in lt:
            return region
    return ""


def _classify_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


def _resolve_year_for_md(month: int, day: int) -> int:
    """Suy năm cho date không có year: nếu ngày đã qua trong năm hiện tại → năm sau."""
    today = date.today()
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year if candidate >= today else today.year + 1


def _parse_date_range(text: str) -> tuple[date | None, date | None]:
    """Parse các format ngày:
        "20 May 2026 - 10 Jun 2026"   ← vietnam.travel
        "01 Jun 2026 - 30 Jun 2026"
        "6 Mar–9 Mar"                 ← visitvietnams.com (KHÔNG có năm) ⭐
        "15 Apr–19 Apr"               ← visitvietnams.com
        "Jun 15, 2026"
        "2026-06-05 to 2026-06-07"    ← ISO fallback
        "5 - 7 Jun, 2026"             ← cũ
    Trả (start, end). Nếu chỉ 1 ngày → start == end.
    Auto-resolve year nếu không có (chọn current year hoặc next nếu đã qua).
    """
    if not text:
        return None, None
    t = text.strip()

    # Format CHÍNH cho VT: "DD MMM YYYY - DD MMM YYYY" (có năm ở cả 2)
    m = re.search(
        r"(\d{1,2})\s+(\w+)\s+(\d{4})\s*[-–to]+\s*(\d{1,2})\s+(\w+)\s+(\d{4})",
        t, re.IGNORECASE,
    )
    if m:
        try:
            d1, mo1_str, yr1 = int(m.group(1)), m.group(2), int(m.group(3))
            d2, mo2_str, yr2 = int(m.group(4)), m.group(5), int(m.group(6))
            mo1 = _month_to_num(mo1_str)
            mo2 = _month_to_num(mo2_str)
            if mo1 and mo2:
                return date(yr1, mo1, d1), date(yr2, mo2, d2)
        except ValueError:
            pass

    # Format CHÍNH cho VV: "DD MMM–DD MMM" (KHÔNG có năm) ⭐
    # Vd "6 Mar–9 Mar", "15 Apr–19 Apr", "11 Feb–14 Feb"
    m = re.search(
        r"(\d{1,2})\s+(\w+)\s*[-–]\s*(\d{1,2})\s+(\w+)(?!\s*\d{4})",
        t, re.IGNORECASE,
    )
    if m:
        try:
            d1 = int(m.group(1))
            mo1 = _month_to_num(m.group(2))
            d2 = int(m.group(3))
            mo2 = _month_to_num(m.group(4))
            if mo1 and mo2:
                yr = _resolve_year_for_md(mo1, d1)
                # Nếu month_end < month_start → cross-year (rare)
                yr2 = yr if mo2 >= mo1 else yr + 1
                return date(yr, mo1, d1), date(yr2, mo2, d2)
        except ValueError:
            pass

    # Format ISO "2026-06-05 to 2026-06-07"
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})\s*(?:to|–|-)\s*(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        try:
            return (
                date(int(m.group(1)), int(m.group(2)), int(m.group(3))),
                date(int(m.group(4)), int(m.group(5)), int(m.group(6))),
            )
        except ValueError:
            return None, None

    # Format "5 - 7 Jun, 2026" (cùng tháng)
    m = re.search(
        r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s+(\w+)[,\s]+(\d{4})",
        t,
    )
    if m:
        try:
            d1, d2 = int(m.group(1)), int(m.group(2))
            mo = _month_to_num(m.group(3))
            yr = int(m.group(4))
            if mo:
                return date(yr, mo, d1), date(yr, mo, d2)
        except ValueError:
            pass

    # Format đơn ngày "Jun 15, 2026" hoặc "15 Jun 2026"
    m = re.search(r"(?:(\d{1,2})\s+(\w+)|(\w+)\s+(\d{1,2}))[,\s]+(\d{4})", t)
    if m:
        try:
            if m.group(1):
                d1, mo_str, yr = int(m.group(1)), m.group(2), int(m.group(5))
            else:
                d1, mo_str, yr = int(m.group(4)), m.group(3), int(m.group(5))
            mo = _month_to_num(mo_str)
            if mo:
                d = date(yr, mo, d1)
                return d, d
        except ValueError:
            pass

    # Format đơn ngày KHÔNG năm: "15 Apr" hoặc "Apr 15"
    m = re.search(r"(?:(\d{1,2})\s+(\w{3,9})|(\w{3,9})\s+(\d{1,2}))(?!\s*[,\s]+\d{4})", t)
    if m:
        try:
            if m.group(1):
                d1, mo_str = int(m.group(1)), m.group(2)
            else:
                d1, mo_str = int(m.group(4)), m.group(3)
            mo = _month_to_num(mo_str)
            if mo:
                yr = _resolve_year_for_md(mo, d1)
                d = date(yr, mo, d1)
                return d, d
        except ValueError:
            pass

    return None, None


def _month_to_num(s: str) -> int | None:
    s = s.lower().strip()[:3]
    for i, name in enumerate(_MONTH_SLUG, start=1):
        if name == s:
            return i
    return None


def _try_get(url: str, client, timeout: float) -> tuple[str | None, str | None]:
    """1 lần GET với timeout cụ thể. Trả (html, error_type).

    Jina AI Reader (r.jina.ai) cần header `X-Return-Format: html` nếu muốn raw
    HTML thay vì markdown — mặc định trả markdown.
    """
    try:
        # r.jina.ai cần X-Return-Format header để trả raw HTML
        headers_override = None
        if "r.jina.ai/" in url:
            headers_override = {"X-Return-Format": "html"}
        r = client.get(url, timeout=timeout, headers=headers_override)
        if r.status_code == 200:
            text = r.text
            # allorigins-get JSON wrapper: {"contents": "...html..."}
            if "allorigins.win/get" in url and text.startswith("{"):
                try:
                    import json
                    data = json.loads(text)
                    text = data.get("contents", "")
                except Exception:  # noqa: BLE001
                    pass
            return text, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def _fetch(url: str, client) -> str | None:
    """Fail-fast multi-provider fetch.

    Strategy:
      1. Direct (5s timeout) — nếu network OK, không tốn time.
      2. Thử lần lượt 5 proxy providers (15s mỗi cái).
      3. Sleep RATE_LIMIT_SEC chỉ sau khi thành công (không sleep sau fail
         để không kéo dài chain proxy fail).

    Worst case (cả direct + 5 proxy fail): ~80s/url. Best case: <1s direct.
    Trung bình khi direct fail: 5 + 1-3 × 15s = ~20-50s/url.
    """
    # Pass 1: direct
    html, err = _try_get(url, client, DIRECT_TIMEOUT_SEC)
    if html:
        time.sleep(RATE_LIMIT_SEC)
        return html
    logger.info("Direct fail (%s) — try %d proxies", err, len(PROXY_PROVIDERS))

    # Pass 2: thử proxy chain
    for name, build_fn in PROXY_PROVIDERS:
        proxy_url = build_fn(url)
        html, err = _try_get(proxy_url, client, PROXY_TIMEOUT_SEC)
        if html:
            logger.info("Proxy [%s] OK (HTML %d bytes)", name, len(html))
            time.sleep(RATE_LIMIT_SEC)
            return html
        logger.info("Proxy [%s] fail: %s", name, err)

    logger.warning("All providers fail for %s", url)
    return None


def _is_markdown(content: str) -> bool:
    """Detect Jina Reader markdown output vs raw HTML."""
    if not content:
        return False
    head = content[:500].lstrip().lower()
    # Markdown markers: bullet, link syntax, heading, không có <html> hay <body>
    if "<html" in head or "<body" in head or "<!doctype" in head:
        return False
    return ("](" in content[:2000]) or content.lstrip().startswith(("# ", "* ", "- ", "**"))


def _parse_markdown_for_events(content: str, detail_prefix: str, base_url: str) -> list[dict[str, Any]]:
    """Parse Jina Reader markdown output cho event detail URLs.

    Strategy block-based (tránh leak data giữa các event):
      1. Find all detail links — record (position, name, url).
      2. Mỗi link i → block = content TỪ link[i-1].end (hoặc 0) ĐẾN link[i+1].start (hoặc end).
         - Phần TRƯỚC link[i] = image cho event này (layout vietnam.travel: ![img] trước [name])
         - Phần SAU link[i] = date + location
      3. Image preference: image gần TRƯỚC link[i] nhất (cùng card).
    """
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Step 1: collect all detail link positions
    link_pattern = re.compile(
        r"\[([^\]\n]+?)\]\((" + re.escape(detail_prefix) + r"[^\s)]+?)\)",
    )
    matches = list(link_pattern.finditer(content))
    if not matches:
        return events

    # Step 2: cho mỗi link, define block boundary
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        url_path = m.group(2).strip()
        path_clean = url_path.split("?", 1)[0]
        slug = path_clean.split(detail_prefix, 1)[1].split("/")[0].strip()
        if not slug or slug in seen:
            continue
        if not name or len(name) < 3:
            continue
        seen.add(slug)

        # Block bound: từ end của link trước (hoặc 0) đến start của link kế (hoặc end)
        block_start = matches[i - 1].end() if i > 0 else 0
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block = content[block_start:block_end]

        # Image: ![alt](url) trong block, ưu tiên cái gần TRƯỚC link[i] (trên cùng card).
        # Đa số layout: image → name → date → location.
        # Lấy image cuối cùng XẢY RA TRƯỚC link[i] trong block.
        image_url = ""
        before_link_in_block = content[block_start:m.start()]
        img_matches = re.findall(r"!\[[^\]]*?\]\((https?://[^\s)]+?)\)", before_link_in_block)
        if img_matches:
            image_url = img_matches[-1]
        else:
            # Fallback: image đầu tiên SAU link (layout name → image)
            after_link_in_block = content[m.end():block_end]
            img_matches = re.findall(r"!\[[^\]]*?\]\((https?://[^\s)]+?)\)", after_link_in_block)
            if img_matches:
                image_url = img_matches[0]

        # Date text: scan trong block (ưu tiên SAU link)
        date_text = ""
        after_link_in_block = content[m.end():block_end]
        date_match = re.search(
            r"\d{1,2}\s+\w{3,9}(?:\s+\d{4})?\s*[-–to]+\s*\d{1,2}\s+\w{3,9}(?:\s+\d{4})?",
            after_link_in_block, re.IGNORECASE,
        )
        if not date_match:
            date_match = re.search(
                r"\d{1,2}\s+\w{3,9}(?:\s+\d{4})?\s*[-–to]+\s*\d{1,2}\s+\w{3,9}(?:\s+\d{4})?",
                block, re.IGNORECASE,
            )
        if date_match:
            date_text = date_match.group(0).strip()
        else:
            single = re.search(r"\d{1,2}\s+\w{3,9}(?:\s+\d{4})?", after_link_in_block, re.IGNORECASE)
            if not single:
                single = re.search(r"\d{1,2}\s+\w{3,9}(?:\s+\d{4})?", block, re.IGNORECASE)
            if single:
                date_text = single.group(0).strip()

        # Location: trong block (sau link ưu tiên)
        location_text = ""
        for area in (after_link_in_block, block):
            area_low = area.lower()
            best_idx = -1
            best_kw = ""
            for kw in _VN_PROVINCE_KEYWORDS:
                idx = area_low.find(kw)
                if idx >= 0 and (best_idx < 0 or idx < best_idx):
                    best_idx = idx
                    best_kw = area[idx:idx + len(kw)]
            if best_kw:
                location_text = best_kw.title()
                break

        url = urljoin(base_url, url_path)
        events.append({
            "slug": slug,
            "name": name,
            "date_text": date_text,
            "location": location_text,
            "image_url": image_url,
            "source_url": url,
        })

    return events


def _parse_list_page(html: str) -> list[dict[str, Any]]:
    """Parse listing page — auto-detect HTML vs markdown (Jina Reader output).

    Pipeline:
      1. Markdown? → _parse_markdown_for_events
      2. HTML → selectolax với link-based extraction
    """
    if _is_markdown(html):
        events = _parse_markdown_for_events(html, DETAIL_PATH_PREFIX, BASE_URL)
        logger.info("Parsed (markdown mode): %d event", len(events))
        return events

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    events: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    # Tìm mọi link tới festival detail page
    detail_links = tree.css(f'a[href*="{DETAIL_PATH_PREFIX}"]')
    logger.info("Parsed (html mode): %d detail link trên trang", len(detail_links))

    for link in detail_links:
        try:
            href = link.attributes.get("href", "")
            if not href or DETAIL_PATH_PREFIX not in href:
                continue
            # Extract slug từ URL (giữa /festival-event/ và ?param/end)
            path = href.split(DETAIL_PATH_PREFIX, 1)[1]
            slug = path.split("?")[0].split("/")[0].strip()
            if not slug or slug in seen_slugs:
                continue

            # Name = text của anchor (đã filter link không có text trống)
            name = (link.text(strip=True) or "").strip()
            if not name:
                # Có thể anchor chỉ wrap image, lấy alt của img bên trong
                img_inside = link.css_first("img")
                if img_inside:
                    name = (img_inside.attributes.get("alt") or "").strip()
            if not name:
                continue

            url = urljoin(BASE_URL, href)

            # Traverse parent (max 5 levels) để tìm container chứa info bổ sung
            parent = link.parent
            depth = 0
            container = parent
            while parent is not None and depth < 5:
                container = parent
                parent = parent.parent
                depth += 1

            # Date text: tìm text node match "DD MMM YYYY" hoặc range
            date_text = _extract_date_text_near(container, name)

            # Location: tìm trong container các từ tỉnh VN ngắn (Ninh Binh, Hue, ...)
            location_text = _extract_location_near(container, name, date_text)

            # Image: img gần link nhất (anchor chính nó nếu wrap, không thì sibling)
            image_url = ""
            img_node = link.css_first("img") or (container.css_first("img") if container else None)
            if img_node:
                src = (
                    img_node.attributes.get("src")
                    or img_node.attributes.get("data-src")
                    or img_node.attributes.get("srcset", "").split()[0] if img_node.attributes.get("srcset") else ""
                )
                if src:
                    # Một số URL bắt đầu bằng "//image.vietnam.travel/..." → cần "https:" prefix
                    if src.startswith("//"):
                        image_url = "https:" + src
                    elif src.startswith("/"):
                        image_url = urljoin(BASE_URL, src)
                    else:
                        image_url = src

            seen_slugs.add(slug)
            events.append({
                "slug": slug,
                "name": name,
                "date_text": date_text,
                "location": location_text,
                "image_url": image_url,
                "source_url": url,
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("Parse 1 link lỗi: %s", e)
            continue

    return events


def _extract_date_text_near(container, exclude_text: str) -> str:
    """Tìm text trong container chứa pattern ngày tháng.

    Pattern phổ biến: "DD MMM YYYY - DD MMM YYYY" hoặc "DD MMM YYYY".
    """
    if not container:
        return ""
    # Lấy tất cả text node (không phải text con thẻ a — vì đó là name)
    text = container.text(separator=" ", strip=True)
    if not text:
        return ""
    # Bỏ exclude_text khỏi text để regex không match tên event
    if exclude_text:
        text = text.replace(exclude_text, " ")
    # Match "20 May 2026 - 10 Jun 2026" hoặc đơn ngày "20 May 2026"
    m = re.search(
        r"\d{1,2}\s+\w{3,9}\s+\d{4}\s*[-–to]+\s*\d{1,2}\s+\w{3,9}\s+\d{4}",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(0).strip()
    m = re.search(r"\d{1,2}\s+\w{3,9}\s+\d{4}", text, re.IGNORECASE)
    if m:
        return m.group(0).strip()
    return ""


# Danh sách tỉnh VN viết tắt + có dấu (lowercase) để extract location.
# Match theo substring trong text container.
_VN_PROVINCE_KEYWORDS = [
    "ninh binh", "hue", "da nang", "hanoi", "ha noi", "ho chi minh", "saigon",
    "nha trang", "khanh hoa", "phu quoc", "kien giang", "vung tau", "can tho",
    "hoi an", "quang nam", "sapa", "lao cai", "ha long", "quang ninh",
    "phong nha", "quang binh", "buon ma thuot", "dak lak", "da lat", "lam dong",
    "phu yen", "binh thuan", "phan thiet", "mui ne", "ca mau", "bac lieu",
    "hai phong", "nam dinh", "ninh thuan", "binh dinh", "quy nhon",
    "vietnam", "viet nam", "northern", "central", "southern", "north", "south",
]


def _extract_location_near(container, exclude_text: str, exclude_date: str) -> str:
    """Tìm tỉnh/thành VN xuất hiện trong text container, không trùng tên event/ngày."""
    if not container:
        return ""
    text = container.text(separator=" ", strip=True)
    if not text:
        return ""
    if exclude_text:
        text = text.replace(exclude_text, " ")
    if exclude_date:
        text = text.replace(exclude_date, " ")
    low = text.lower()
    # Match keyword đầu tiên xuất hiện
    found = []
    for kw in _VN_PROVINCE_KEYWORDS:
        if kw in low:
            # Trả về dạng đúng case từ text gốc
            idx = low.find(kw)
            found.append((idx, text[idx:idx + len(kw)]))
    if not found:
        return ""
    # Chọn keyword xuất hiện đầu tiên (gần card hơn)
    found.sort(key=lambda x: x[0])
    return found[0][1].title()


def _parse_detail_page(html: str) -> dict[str, str]:
    """Parse trang detail → description chi tiết (Phase 1 chỉ lấy mô tả).

    Vietnam.travel detail page không có class CSS đặc trưng — lấy text
    body chính bằng cách find paragraphs trong main content. Heuristic:
    paragraph dài nhất là description.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    # Thử các selector phổ biến trước
    desc_node = (
        tree.css_first("div.field--name-body")
        or tree.css_first("div.event-description")
        or tree.css_first("article .content")
        or tree.css_first("main p")
    )
    if desc_node:
        description = desc_node.text(separator=" ", strip=True)
    else:
        # Fallback: lấy paragraph dài nhất trong main
        paragraphs = tree.css("main p, article p, div p")
        if paragraphs:
            best = max(paragraphs, key=lambda p: len(p.text() or ""))
            description = (best.text(separator=" ", strip=True) or "")
        else:
            description = ""
    return {"description": description[:4000]}


def _fetch_from_gas_proxy(proxy_url: str, years: list[int]) -> list[dict[str, Any]]:
    """Fetch events từ Google Apps Script Web App proxy.

    Apps Script trả JSON:
      {
        "fetched_at": "...",
        "source": "all",
        "years": [2026, 2027],
        "total": 123,
        "events": [
          {
            "source": "vietnam-travel" | "visitvietnams",
            "slug": "ninh-binh-tourism-week-2026",
            "name": "Ninh Binh Tourism Week 2026",
            "date_text": "20 May 2026 - 10 Jun 2026",
            "location": "Ninh Binh",
            "description": "...",
            "image_url": "https://...",
            "source_url": "https://..."
          }, ...
        ],
        "errors": [...]
      }
    """
    import httpx

    years_str = ",".join(str(y) for y in years)
    url = f"{proxy_url}?source=all&years={years_str}"
    logger.info("GAS proxy fetch: %s", url)

    # Apps Script có thể redirect → follow
    # Timeout dài vì script có thể chạy 30-60s
    with httpx.Client(follow_redirects=True, timeout=180.0) as client:
        r = client.get(url)
        if r.status_code != 200:
            logger.warning("GAS proxy HTTP %d: %s", r.status_code, r.text[:200])
            return []
        import json
        try:
            data = json.loads(r.text)
        except Exception as e:  # noqa: BLE001
            logger.warning("GAS proxy JSON parse fail: %s", e)
            return []
        raw_events = data.get("events", [])
        errors = data.get("errors", [])
        if errors:
            logger.info("GAS proxy reported errors: %s", errors)

        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for ev in raw_events:
            slug = ev.get("slug", "")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            # Parse date_text → date_start/end
            today = datetime.now()
            d_start, d_end = _parse_date_range(ev.get("date_text", ""))
            if not d_start:
                # Fallback: ngày đầu năm hiện tại
                d_start = date(today.year, 1, 1)
                d_end = d_start
            enriched = {
                "slug": slug,
                "name": ev.get("name", "")[:512],
                "date_text": ev.get("date_text", ""),
                "date_start": d_start,
                "date_end": d_end or d_start,
                "location": ev.get("location", "")[:256],
                "description": ev.get("description", "")[:4000],
                "image_url": ev.get("image_url", "")[:1024],
                "source_url": ev.get("source_url", "")[:1024],
                "region": _classify_region(ev.get("location", "")),
                "category": _classify_category(ev.get("name", ""), ev.get("description", "")),
            }
            out.append(enriched)
        return out


def _build_http_client(httpx_):
    """Build httpx Client với headers + per-call timeout (override mỗi GET)."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    # Timeout per-call (override trong _try_get). Default đặt 30s phòng hờ.
    return httpx_.Client(
        headers=headers,
        follow_redirects=True,
        timeout=httpx_.Timeout(30.0),
    )


def _enrich_event(ev: dict[str, Any], fallback_year: int, fallback_month: int, client) -> dict[str, Any] | None:
    """Parse date_text → date_start/end, classify region+category, fetch detail.
    Trả None nếu không suy được date.
    """
    d_start, d_end = _parse_date_range(ev.get("date_text", ""))
    if not d_start:
        try:
            d_start = date(fallback_year, fallback_month, 1)
            d_end = d_start
        except ValueError:
            return None
    ev["date_start"] = d_start
    ev["date_end"] = d_end or d_start
    ev["region"] = _classify_region(ev.get("location", ""))
    ev["category"] = _classify_category(ev.get("name", ""))

    # Detail page (best effort, không block nếu fail)
    detail_html = _fetch(ev["source_url"], client)
    if detail_html:
        try:
            detail = _parse_detail_page(detail_html)
            ev["description"] = detail.get("description", "")
        except Exception:  # noqa: BLE001
            ev["description"] = ""
    else:
        ev["description"] = ""
    return ev


def scrape_festivals(years: list[int] | None = None) -> list[dict[str, Any]]:
    """Crawl 2 nguồn vietnam.travel + visitvietnams.com.

    Priority 1: FESTIVAL_PROXY_URL env var (Google Apps Script Web App).
       Nếu set, fetch JSON từ URL này → instant data, không cần parse HTML.
    Priority 2: Direct + proxy chain (Jina, allorigins, ...).
    """
    import httpx

    today = datetime.now()
    if years is None:
        years = [today.year, today.year + 1]

    # ── Priority 1: Google Apps Script Proxy ────────────────────────────
    proxy_url = (os.environ.get("FESTIVAL_PROXY_URL") or "").strip()
    if proxy_url:
        logger.info("FESTIVAL_PROXY_URL set → dùng Google Apps Script proxy")
        try:
            events = _fetch_from_gas_proxy(proxy_url, years)
            if events:
                logger.info("[GAS Proxy] xong: %d event", len(events))
                return events
            logger.warning("[GAS Proxy] trả 0 event — fallback HTML scrape")
        except Exception as e:  # noqa: BLE001
            logger.warning("[GAS Proxy] lỗi: %s — fallback HTML scrape", e)

    # ── Priority 2: HTML scrape qua proxy chain ─────────────────────────
    seen_slugs: set[str] = set()
    out: list[dict[str, Any]] = []

    with _build_http_client(httpx) as client:
        # ── Source 1: vietnam.travel ────────────────────────────────────
        vt_ok = 0
        vt_fail = 0
        for year in years:
            for month_idx, month_slug in enumerate(_MONTH_SLUG, start=1):
                url = f"{EVENT_LIST_URL}?month={month_slug}&year={year}"
                html = _fetch(url, client)
                if not html:
                    vt_fail += 1
                    continue
                events = _parse_list_page(html)
                logger.info(
                    "[VT] %s/%s: %d event (HTML %d bytes)",
                    month_slug, year, len(events), len(html),
                )
                vt_ok += 1
                for ev in events:
                    if ev["slug"] in seen_slugs:
                        continue
                    seen_slugs.add(ev["slug"])
                    enriched = _enrich_event(ev, year, month_idx, client)
                    if enriched:
                        out.append(enriched)
        logger.info("[VT] xong: %d list page OK, %d fail, %d event mới", vt_ok, vt_fail, len(out))

        # ── Source 2: visitvietnams.com ─────────────────────────────────
        # LUÔN chạy (không conditional) — vietnam.travel rất khó reach từ Render.
        # VV có thể bổ sung event mà VT không có hoặc reverse.
        logger.info("[VV] Bắt đầu scrape visitvietnams.com (VT đã được: %d event, %d/%d page OK)", len(out), vt_ok, vt_ok + vt_fail)
        vv_count = _scrape_visitvietnams(client, seen_slugs, out, years[0])
        logger.info("[VV] xong: thêm %d event", vv_count)

    logger.info("Festival scrape xong: %d event tổng", len(out))
    return out


def _scrape_visitvietnams(client, seen_slugs: set[str], out: list[dict[str, Any]], default_year: int) -> int:
    """Scrape visitvietnams.com /en/events. Trả số event mới thêm vào out.

    VV thường là SPA — direct fetch trả skeleton HTML không có content. Force
    qua Jina Reader để get server-side rendered content (markdown).
    """
    added = 0
    for page in range(1, VV_MAX_PAGES + 1):
        target = f"{VV_EVENT_LIST_URL}?page={page}&keyword="
        # Force qua Jina Reader (skip direct cho VV vì SPA)
        url = f"https://r.jina.ai/{target}"
        html = _fetch(url, client)
        if not html:
            logger.info("[VV] page %d: fetch fail, dừng pagination", page)
            break
        events = _parse_visitvietnams_list(html)
        logger.info("[VV] page %d: %d event (HTML %d bytes)", page, len(events), len(html))
        if not events:
            # Empty page = hết, dừng
            break
        page_added = 0
        for ev in events:
            slug = ev.get("slug")
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            # Default fallback: tháng hiện tại của default_year
            enriched = _enrich_event(ev, default_year, datetime.now().month, client)
            if enriched:
                out.append(enriched)
                added += 1
                page_added += 1
        if page_added == 0:
            # Page không thêm event mới (toàn dup) → có thể đến cuối, dừng
            break
    return added


def _parse_visitvietnams_list(html: str) -> list[dict[str, Any]]:
    """Parse VV listing — auto-detect markdown (Jina) vs HTML."""
    if _is_markdown(html):
        events = _parse_markdown_for_events(html, VV_DETAIL_PATH_PREFIXES[0], VV_BASE_URL)
        # Slug prefix "vv-" để không đụng VT
        for ev in events:
            ev["slug"] = f"vv-{ev['slug']}"
        logger.info("[VV] Parsed (markdown mode): %d event", len(events))
        return events

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Tìm mọi link tới detail (thử nhiều prefix vì không chắc structure)
    detail_links = []
    for prefix in VV_DETAIL_PATH_PREFIXES:
        detail_links.extend(tree.css(f'a[href*="{prefix}"]'))

    for link in detail_links:
        try:
            href = link.attributes.get("href", "")
            if not href:
                continue
            # Skip nếu href là chính path prefix (listing page link, không phải detail)
            is_detail = False
            slug = ""
            for prefix in VV_DETAIL_PATH_PREFIXES:
                if prefix in href:
                    path = href.split(prefix, 1)[1]
                    candidate = path.split("?")[0].split("/")[0].strip()
                    if candidate:
                        is_detail = True
                        slug = candidate
                        break
            if not is_detail or not slug or slug in seen:
                continue

            name = (link.text(strip=True) or "").strip()
            if not name:
                img_inside = link.css_first("img")
                if img_inside:
                    name = (img_inside.attributes.get("alt") or "").strip()
            if not name or len(name) < 3:
                continue

            url = urljoin(VV_BASE_URL, href)

            # Traverse parent để tìm date + image
            parent = link.parent
            depth = 0
            container = parent
            while parent is not None and depth < 5:
                container = parent
                parent = parent.parent
                depth += 1

            date_text = _extract_date_text_near(container, name)
            location_text = _extract_location_near(container, name, date_text)

            image_url = ""
            img_node = link.css_first("img") or (container.css_first("img") if container else None)
            if img_node:
                src = img_node.attributes.get("src") or img_node.attributes.get("data-src", "")
                if src:
                    if src.startswith("//"):
                        image_url = "https:" + src
                    elif src.startswith("/"):
                        image_url = urljoin(VV_BASE_URL, src)
                    else:
                        image_url = src

            seen.add(slug)
            events.append({
                "slug": f"vv-{slug}",  # prefix để tránh đụng vietnam.travel slug
                "name": name,
                "date_text": date_text,
                "location": location_text,
                "image_url": image_url,
                "source_url": url,
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("[VV] parse 1 link lỗi: %s", e)
            continue

    return events


def save_festivals_to_db(db, events: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert events vào DB. Hash-based skip nếu content không đổi."""
    from models import Festival

    inserted = 0
    updated = 0
    unchanged = 0
    now = datetime.utcnow()

    for ev in events:
        slug = ev["slug"]
        if not slug:
            continue
        content_hash = _compute_hash(
            ev.get("name", ""),
            str(ev.get("date_start") or ""),
            str(ev.get("date_end") or ""),
            ev.get("location", ""),
            ev.get("description", "")[:1000],
        )
        existing = db.query(Festival).filter(Festival.slug == slug).first()
        if existing:
            if existing.content_hash == content_hash:
                unchanged += 1
                continue
            existing.name_vi = ev["name"][:512]
            existing.date_start = ev["date_start"]
            existing.date_end = ev["date_end"]
            existing.location_text = (ev.get("location") or "")[:256]
            existing.region = ev.get("region", "")
            existing.category = ev.get("category", "other")
            existing.description = ev.get("description", "")
            existing.image_url = (ev.get("image_url") or "")[:1024]
            existing.source_url = (ev.get("source_url") or "")[:1024]
            existing.content_hash = content_hash
            existing.scraped_at = now
            updated += 1
        else:
            f = Festival(
                slug=slug,
                name_vi=ev["name"][:512],
                date_start=ev["date_start"],
                date_end=ev["date_end"],
                location_text=(ev.get("location") or "")[:256],
                region=ev.get("region", ""),
                category=ev.get("category", "other"),
                description=ev.get("description", ""),
                image_url=(ev.get("image_url") or "")[:1024],
                source_url=(ev.get("source_url") or "")[:1024],
                content_hash=content_hash,
                scraped_at=now,
            )
            db.add(f)
            inserted += 1

    db.commit()
    logger.info(
        "Festival save: inserted=%d updated=%d unchanged=%d",
        inserted, updated, unchanged,
    )
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


def run_festival_scrape(db) -> dict[str, int]:
    """Top-level: scrape + save. Dùng cho cron weekly + manual trigger."""
    events = scrape_festivals()
    return save_festivals_to_db(db, events)
