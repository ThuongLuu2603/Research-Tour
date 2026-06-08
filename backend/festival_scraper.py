"""Scrape lehoivietnam.com.vn — Sự kiện & Lễ hội VN (Phase 1.3 — site mới).

Lý do đổi source:
  - vietnam.travel + visitvietnams.com: Render bị Cloudflare block.
  - lehoivietnam.com.vn: 2,953 lễ nội địa + 152 lễ quốc tế. Robots.txt allow,
    không có WAF aggressive. Direct fetch nên work từ Render.

URL patterns:
  - Listing domestic: /vi/kham-pha?page=N  (247 pages × ~12 = ~2,953 events)
  - Listing intl:     /vi/kham-pha?scope=intl&page=N  (13 pages × ~12 = ~152 events)
  - Detail:           /vi/su-kien/{id}-{slug}-{digits}

CSS selectors (HTML đã verify từ user):
  article.lh-event-item — wrapper mỗi card
  a.lh-event-item-media (href=detail, có img + badge)
    img — src, alt (= name)
    span.lh-event-item-badge — status ("Sắp diễn ra")
  div.lh-event-item-body
    div.lh-event-item-head > h3 > a — title + href detail
    div.lh-event-item-meta-chip-wrap
      a.lh-event-chip.lh-loc-link — location (có thể 2: phường + tỉnh)
      span.lh-event-chip — date text "15/8 - 2/9"
    p — description snippet
    div.lh-event-item-stats — "cập nhật X ngày trước"
    div.lh-event-item-foot > a.lh-btn — CTA

Fallback: nếu direct fail, dùng r.jina.ai (đã verify work) trả markdown.

Tần suất: weekly cron.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BASE_URL = "https://lehoivietnam.com.vn"
LIST_URL_DOMESTIC = f"{BASE_URL}/vi/kham-pha"  # ?page=N
LIST_URL_INTL = f"{BASE_URL}/vi/kham-pha"      # ?scope=intl&page=N
DETAIL_PATH_PREFIX = "/vi/su-kien/"

# Default: scrape 30 page domestic (~360 event) + all 13 page intl (~152 event).
# Configurable qua env vars FESTIVAL_MAX_DOMESTIC_PAGES / FESTIVAL_MAX_INTL_PAGES.
DEFAULT_MAX_DOMESTIC_PAGES = 30
DEFAULT_MAX_INTL_PAGES = 13

# User-Agent browser-like (lehoivietnam có vẻ không có WAF aggressive nhưng vẫn safe).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DIRECT_TIMEOUT_SEC = 30.0
JINA_TIMEOUT_SEC = 45.0
RATE_LIMIT_SEC = 1.0  # Polite — 1 req/giây

EXPAND_MONTHS_AHEAD = 12

# ── Province + region map (VN) ───────────────────────────────────────────

# Map keyword tỉnh/thành lowercase → region (bac/trung/nam).
# Cover toàn bộ 63 tỉnh (chỉ tên ngắn để match nhanh).
_REGION_BY_PROVINCE_KEYWORD: dict[str, str] = {
    # Bắc Bộ
    "hà nội": "bac", "ha noi": "bac", "hanoi": "bac",
    "hải phòng": "bac", "hai phong": "bac",
    "quảng ninh": "bac", "quang ninh": "bac", "hạ long": "bac", "ha long": "bac",
    "lào cai": "bac", "lao cai": "bac", "sapa": "bac", "sa pa": "bac",
    "ninh bình": "bac", "ninh binh": "bac", "tràng an": "bac", "trang an": "bac",
    "hà giang": "bac", "ha giang": "bac",
    "thái nguyên": "bac", "thai nguyen": "bac",
    "bắc ninh": "bac", "bac ninh": "bac",
    "phú thọ": "bac", "phu tho": "bac",
    "yên bái": "bac", "yen bai": "bac", "mù cang chải": "bac", "mu cang chai": "bac",
    "điện biên": "bac", "dien bien": "bac",
    "lạng sơn": "bac", "lang son": "bac",
    "tuyên quang": "bac", "tuyen quang": "bac",
    "bắc giang": "bac", "bac giang": "bac",
    "bắc kạn": "bac", "bac kan": "bac",
    "cao bằng": "bac", "cao bang": "bac",
    "hòa bình": "bac", "hoa binh": "bac",
    "hải dương": "bac", "hai duong": "bac",
    "hưng yên": "bac", "hung yen": "bac",
    "lai châu": "bac", "lai chau": "bac",
    "nam định": "bac", "nam dinh": "bac",
    "nghệ an": "bac", "nghe an": "bac",
    "sơn la": "bac", "son la": "bac",
    "thái bình": "bac", "thai binh": "bac",
    "thanh hóa": "bac", "thanh hoa": "bac",
    "vĩnh phúc": "bac", "vinh phuc": "bac",
    "hà nam": "bac", "ha nam": "bac",
    # Trung Bộ
    "huế": "trung", "hue": "trung", "thừa thiên": "trung", "thua thien": "trung",
    "đà nẵng": "trung", "da nang": "trung",
    "quảng nam": "trung", "quang nam": "trung", "hội an": "trung", "hoi an": "trung",
    "quảng bình": "trung", "quang binh": "trung", "phong nha": "trung",
    "quảng trị": "trung", "quang tri": "trung",
    "khánh hòa": "trung", "khanh hoa": "trung", "nha trang": "trung",
    "phú yên": "trung", "phu yen": "trung",
    "bình định": "trung", "binh dinh": "trung", "quy nhơn": "trung", "quy nhon": "trung",
    "ninh thuận": "trung", "ninh thuan": "trung",
    "bình thuận": "trung", "binh thuan": "trung", "phan thiết": "trung", "phan thiet": "trung", "mũi né": "trung", "mui ne": "trung",
    "đà lạt": "trung", "da lat": "trung", "dalat": "trung", "lâm đồng": "trung", "lam dong": "trung",
    "kon tum": "trung",
    "gia lai": "trung", "pleiku": "trung",
    "đắk lắk": "trung", "dak lak": "trung", "buôn ma thuột": "trung", "buon ma thuot": "trung",
    "đắk nông": "trung", "dak nong": "trung",
    "quảng ngãi": "trung", "quang ngai": "trung",
    "hà tĩnh": "trung", "ha tinh": "trung",
    # Nam Bộ
    "tp.hcm": "nam", "tphcm": "nam", "tp hcm": "nam", "hồ chí minh": "nam", "ho chi minh": "nam",
    "saigon": "nam", "sài gòn": "nam", "sg": "nam",
    "cần thơ": "nam", "can tho": "nam",
    "vũng tàu": "nam", "vung tau": "nam", "bà rịa": "nam", "ba ria": "nam",
    "đồng nai": "nam", "dong nai": "nam", "biên hòa": "nam", "bien hoa": "nam",
    "bình dương": "nam", "binh duong": "nam",
    "long an": "nam",
    "tiền giang": "nam", "tien giang": "nam", "mỹ tho": "nam", "my tho": "nam",
    "bến tre": "nam", "ben tre": "nam",
    "vĩnh long": "nam", "vinh long": "nam",
    "an giang": "nam", "châu đốc": "nam", "chau doc": "nam",
    "kiên giang": "nam", "kien giang": "nam", "phú quốc": "nam", "phu quoc": "nam",
    "cà mau": "nam", "ca mau": "nam",
    "sóc trăng": "nam", "soc trang": "nam",
    "trà vinh": "nam", "tra vinh": "nam",
    "đồng tháp": "nam", "dong thap": "nam",
    "hậu giang": "nam", "hau giang": "nam",
    "bạc liêu": "nam", "bac lieu": "nam",
    "bình phước": "nam", "binh phuoc": "nam",
    "tây ninh": "nam", "tay ninh": "nam",
}


def _classify_region(location_text: str) -> str:
    if not location_text:
        return ""
    lt = location_text.lower()
    for kw, region in _REGION_BY_PROVINCE_KEYWORD.items():
        if kw in lt:
            return region
    return ""


# Category keywords (cùng pattern code cũ)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "religious": ["chùa", "đền", "phật", "lễ phật", "lễ chùa", "vu lan", "phật đản", "tâm linh", "lễ tế", "đình"],
    "music":     ["âm nhạc", "festival music", "concert", "ca trù", "quan họ", "đờn ca"],
    "food":      ["ẩm thực", "food", "trà", "cà phê", "ocop", "sầu riêng", "vải", "đặc sản"],
    "sport":     ["thể thao", "marathon", "đua", "chọi trâu", "đua ghe", "đua thuyền", "ironman"],
    "cultural":  ["lễ hội", "truyền thống", "văn hóa", "dân gian", "cổ truyền", "hội", "festival", "carnival"],
}


def _classify_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


def _slugify(s: str) -> str:
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


# ── Date parser cho format "DD/M - DD/M" hoặc "DD/M - DD/M/YYYY" ─────────

def _resolve_year_for_dm(month: int, day: int, today: date) -> int:
    """Suy năm: chọn current nếu ngày chưa qua, năm sau nếu đã qua."""
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year if candidate >= today else today.year + 1


def _parse_lehoi_date(text: str) -> tuple[date | None, date | None]:
    """Parse format ngày tháng lehoivietnam.com.vn:

      "15/8 - 2/9"             → DD/M - DD/M (no year)
      "10 - 15/6"              → DD - DD/M (cùng tháng)
      "15/8 - 2/9/2026"        → DD/M - DD/M/YYYY
      "21/7 - 19/9/2027"
      "19/3-26/9/2027"         → có thể không space
      "11-14/11"               → DD-DD/M
      "15/8/2026"              → DD/M/YYYY (single)
      "15/8"                   → DD/M (single)

    Auto-resolve year nếu không có (theo current vs next year).
    """
    if not text:
        return None, None
    t = text.strip()
    today = date.today()

    # Format 1: "DD/M - DD/M/YYYY" (range với year ở cuối)
    m = re.search(
        r"(\d{1,2})/(\d{1,2})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{4})",
        t,
    )
    if m:
        try:
            d1, mo1 = int(m.group(1)), int(m.group(2))
            d2, mo2, yr2 = int(m.group(3)), int(m.group(4)), int(m.group(5))
            # Year start: nếu mo1 > mo2, cross-year reverse, vd 19/3 → 26/9/2027
            yr1 = yr2 if mo1 <= mo2 else yr2 - 1
            return date(yr1, mo1, d1), date(yr2, mo2, d2)
        except ValueError:
            pass

    # Format 2: "DD/M/YYYY - DD/M/YYYY" (đầy đủ năm 2 đầu)
    m = re.search(
        r"(\d{1,2})/(\d{1,2})/(\d{4})\s*[-–]\s*(\d{1,2})/(\d{1,2})/(\d{4})",
        t,
    )
    if m:
        try:
            return (
                date(int(m.group(3)), int(m.group(2)), int(m.group(1))),
                date(int(m.group(6)), int(m.group(5)), int(m.group(4))),
            )
        except ValueError:
            pass

    # Format 3: "DD/M - DD/M" (no year)
    m = re.search(
        r"(\d{1,2})/(\d{1,2})\s*[-–]\s*(\d{1,2})/(\d{1,2})(?!/?\d)",
        t,
    )
    if m:
        try:
            d1, mo1 = int(m.group(1)), int(m.group(2))
            d2, mo2 = int(m.group(3)), int(m.group(4))
            yr = _resolve_year_for_dm(mo1, d1, today)
            yr2 = yr if mo2 >= mo1 else yr + 1
            return date(yr, mo1, d1), date(yr2, mo2, d2)
        except ValueError:
            pass

    # Format 4: "DD - DD/M" (cùng tháng, vd "10 - 15/6")
    m = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})/(\d{1,2})(?!/?\d)", t)
    if m:
        try:
            d1, d2, mo = int(m.group(1)), int(m.group(2)), int(m.group(3))
            yr = _resolve_year_for_dm(mo, d1, today)
            return date(yr, mo, d1), date(yr, mo, d2)
        except ValueError:
            pass

    # Format 5: "DD-DD/M" (no space)
    m = re.search(r"(\d{1,2})-(\d{1,2})/(\d{1,2})(?!/?\d)", t)
    if m:
        try:
            d1, d2, mo = int(m.group(1)), int(m.group(2)), int(m.group(3))
            yr = _resolve_year_for_dm(mo, d1, today)
            return date(yr, mo, d1), date(yr, mo, d2)
        except ValueError:
            pass

    # Format 6: "DD/M/YYYY" (single với year)
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d, d
        except ValueError:
            pass

    # Format 7: "DD/M" (single no year)
    m = re.search(r"(\d{1,2})/(\d{1,2})(?!/?\d)", t)
    if m:
        try:
            d1, mo = int(m.group(1)), int(m.group(2))
            yr = _resolve_year_for_dm(mo, d1, today)
            d = date(yr, mo, d1)
            return d, d
        except ValueError:
            pass

    return None, None


# ── Fetch ────────────────────────────────────────────────────────────────

def _try_get(url: str, client, timeout: float) -> tuple[str | None, str | None]:
    """1 lần GET với timeout. Trả (html, err)."""
    try:
        r = client.get(url, timeout=timeout)
        if r.status_code == 200:
            return r.text, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:80]}"


def _fetch(url: str, client) -> str | None:
    """Fetch URL — FORCE qua Jina Reader.

    Lý do: lehoivietnam.com.vn là SPA (JavaScript-rendered). Direct fetch
    trả HTTP 200 với HTML skeleton, KHÔNG có article.lh-event-item nào.
    Browser cần execute JS để render cards. Jina Reader chạy headless browser
    nội bộ → trả content sau khi JS render xong.

    Strategy: force Jina ngay từ đầu (tiết kiệm 1 round-trip direct vô ích).
    Direct fallback chỉ kích hoạt nếu Jina trả empty (rare).
    """
    jina_url = f"https://r.jina.ai/{url}"
    html, err = _try_get(jina_url, client, JINA_TIMEOUT_SEC)
    if html and len(html) > 500:  # Min size cho content có nghĩa
        logger.info("Jina OK (%d bytes)", len(html))
        time.sleep(RATE_LIMIT_SEC)
        return html
    logger.info("Jina fail/empty (%s, %d bytes) — thử direct", err, len(html) if html else 0)

    # Direct fallback (rare)
    html, err = _try_get(url, client, DIRECT_TIMEOUT_SEC)
    if html:
        time.sleep(RATE_LIMIT_SEC)
        return html
    logger.warning("Cả Jina + direct fail cho %s: %s", url, err)
    return None


# ── HTML parser (selectolax với CSS selectors thật) ──────────────────────

def _is_markdown(content: str) -> bool:
    """Detect Jina markdown output vs raw HTML."""
    if not content:
        return False
    head = content[:500].lstrip().lower()
    if "<html" in head or "<body" in head or "<!doctype" in head:
        return False
    return ("](" in content[:2000]) or content.lstrip().startswith(("# ", "* ", "- ", "**"))


def _parse_list_page(html: str) -> list[dict[str, Any]]:
    """Parse trang list — auto-detect HTML vs markdown."""
    if _is_markdown(html):
        return _parse_list_page_markdown(html)

    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    # CSS selector EXACT từ HTML user share: article.lh-event-item
    cards = tree.css("article.lh-event-item")
    logger.info("Tìm thấy %d card lh-event-item", len(cards))

    for card in cards:
        try:
            ev = _parse_card_html(card)
            if not ev:
                continue
            if ev["slug"] in seen:
                continue
            seen.add(ev["slug"])
            events.append(ev)
        except Exception as e:  # noqa: BLE001
            logger.debug("Parse 1 card lỗi: %s", e)
            continue

    return events


def _parse_card_html(card) -> dict[str, Any] | None:
    """Parse 1 article.lh-event-item card → dict."""
    # Title + detail URL
    title_node = card.css_first("div.lh-event-item-head h3 a")
    if not title_node:
        title_node = card.css_first("h3 a")
    if not title_node:
        return None
    name = (title_node.text(strip=True) or "").strip()
    href = title_node.attributes.get("href", "")
    if not name or not href or DETAIL_PATH_PREFIX not in href:
        return None
    # Slug = phần sau /vi/su-kien/
    path_after = href.split(DETAIL_PATH_PREFIX, 1)[1]
    slug = path_after.split("?")[0].split("/")[0].strip()
    if not slug:
        return None
    source_url = urljoin(BASE_URL, href)

    # Image — a.lh-event-item-media > img
    image_url = ""
    img_node = card.css_first("a.lh-event-item-media img") or card.css_first("img")
    if img_node:
        src = (
            img_node.attributes.get("src")
            or img_node.attributes.get("data-src")
            or ""
        )
        if src:
            if src.startswith("//"):
                image_url = "https:" + src
            elif src.startswith("/"):
                image_url = urljoin(BASE_URL, src)
            else:
                image_url = src

    # Meta chips: location + date
    # a.lh-event-chip.lh-loc-link → location anchors (có thể 1-2: phường + tỉnh)
    # span.lh-event-chip (không phải link) → date text
    location_chips = card.css("a.lh-event-chip.lh-loc-link")
    locations = [(c.text(strip=True) or "").strip() for c in location_chips if c.text(strip=True)]
    location_text = ", ".join(locations) if locations else ""

    date_text = ""
    span_chips = card.css("span.lh-event-chip")
    for span in span_chips:
        txt = (span.text(strip=True) or "").strip()
        # Heuristic: span chứa "/" và số = date chip
        if re.search(r"\d{1,2}/\d{1,2}", txt):
            date_text = txt
            break

    # Description (p ngay trong lh-event-item-body)
    desc_node = card.css_first("div.lh-event-item-body > p")
    description = (desc_node.text(strip=True) if desc_node else "")[:2000]

    return {
        "slug": slug,
        "name": name[:512],
        "date_text": date_text,
        "location": location_text[:256],
        "description": description,
        "image_url": image_url[:1024],
        "source_url": source_url[:1024],
    }


# ── Markdown parser (Jina fallback) ──────────────────────────────────────

def _parse_list_page_markdown(content: str) -> list[dict[str, Any]]:
    """Parse Jina markdown output cho lehoivietnam list page.

    Strategy block-based với precedence "after link":
      - Tìm tất cả link [name](/vi/su-kien/...).
      - Mỗi link là 1 event. Block = từ link[i-1].end đến link[i+1].start.
      - QUAN TRỌNG: scan date/location/description trong `after_link` TRƯỚC,
        chỉ fallback `block` nếu after_link không có (vì block leak data
        event trước nếu event này không có date riêng).
      - Image: nằm TRƯỚC link (layout image→title).
    """
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    link_pattern = re.compile(
        r"\[([^\]\n]+?)\]\((" + re.escape(DETAIL_PATH_PREFIX) + r"[^\s)]+?)\)",
    )
    matches = list(link_pattern.finditer(content))
    if not matches:
        return events

    # Dedupe: same slug có thể appear 2 lần (anchor image + anchor title)
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        url_path = m.group(2).strip()
        slug = url_path.split(DETAIL_PATH_PREFIX, 1)[1].split("?")[0].split("/")[0].strip()
        if not slug or slug in seen:
            continue
        if not name or len(name) < 3:
            continue
        # Skip nếu name là image alt-like (bắt đầu bằng `!` hoặc URL)
        if name.startswith("!") or name.startswith("http"):
            continue
        seen.add(slug)

        block_start = matches[i - 1].end() if i > 0 else 0
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        before_link = content[block_start:m.start()]
        after_link = content[m.end():block_end]

        # Image: ![](url) cuối cùng TRƯỚC link (layout lehoivietnam: image → title)
        image_url = ""
        img_matches = re.findall(r"!\[[^\]]*?\]\((https?://[^\s)]+?)\)", before_link)
        if img_matches:
            image_url = img_matches[-1]
        else:
            # Fallback after_link
            img_matches = re.findall(r"!\[[^\]]*?\]\((https?://[^\s)]+?)\)", after_link)
            if img_matches:
                image_url = img_matches[0]

        # Date: tìm trong after_link TRƯỚC (after_link = data của event này).
        # Thử các pattern theo độ specific (longest first để tránh "15/6" nuốt "10 - 15/6").
        date_text = ""
        date_patterns = [
            # "DD/M/YYYY - DD/M/YYYY"
            r"\d{1,2}/\d{1,2}/\d{4}\s*[-–]\s*\d{1,2}/\d{1,2}/\d{4}",
            # "DD/M - DD/M/YYYY" (year ở cuối)
            r"\d{1,2}/\d{1,2}\s*[-–]\s*\d{1,2}/\d{1,2}/\d{4}",
            # "DD/M - DD/M" (no year)
            r"\d{1,2}/\d{1,2}\s*[-–]\s*\d{1,2}/\d{1,2}(?!/?\d)",
            # "DD - DD/M" (cùng tháng, no slash on start) ⭐ FIX
            r"\d{1,2}\s*[-–]\s*\d{1,2}/\d{1,2}(?!/?\d)",
            # "DD-DD/M" no space
            r"\d{1,2}-\d{1,2}/\d{1,2}(?!/?\d)",
            # "DD/M/YYYY" single
            r"\d{1,2}/\d{1,2}/\d{4}",
            # "DD/M" single
            r"\d{1,2}/\d{1,2}(?!/?\d)",
        ]
        for scope_text in (after_link, before_link):
            for pat in date_patterns:
                date_match = re.search(pat, scope_text)
                if date_match:
                    date_text = date_match.group(0)
                    break
            if date_text:
                break

        # Location: tìm trong after_link TRƯỚC
        location_text = ""
        for scope_text in (after_link, before_link):
            # Markdown location link: [Đắk Lắk](/vi/dia-diem/...)
            # Chọn link cuối cùng (thường là tỉnh — bao trùm hơn phường/xã)
            loc_matches = re.findall(r"\[([^\]\n]+?)\]\(/vi/dia-diem/[^)]+?\)", scope_text)
            if loc_matches:
                # Ưu tiên match dài hơn / bao trùm hơn (vd "Đắk Lắk" > "Xã Ea Knuếc")
                # Heuristic: lấy match cuối (thường là tỉnh sau phường)
                location_text = loc_matches[-1].strip()
                break
            # Fallback: tìm tỉnh trong text
            scope_low = scope_text.lower()
            for kw in _REGION_BY_PROVINCE_KEYWORD.keys():
                if kw in scope_low:
                    idx = scope_low.find(kw)
                    location_text = scope_text[idx:idx + len(kw)].title()
                    break
            if location_text:
                break

        # Description: trong after_link, cắt tại newline đôi hoặc link kế
        desc = re.split(r"\n{2,}|\[[^\]]+?\]\(/vi/", after_link)[0][:500].strip()
        # Remove dữ liệu "Sắp diễn ra", "cập nhật X ngày trước" — không phải description
        desc = re.sub(r"\b(Sắp diễn ra|Đang diễn ra|Đã kết thúc|cập nhật[^.]*?trước)\b", "", desc).strip()

        events.append({
            "slug": slug,
            "name": name[:512],
            "date_text": date_text,
            "location": location_text[:256],
            "description": desc,
            "image_url": image_url[:1024],
            "source_url": urljoin(BASE_URL, url_path)[:1024],
        })

    logger.info("Parsed markdown: %d event", len(events))
    return events


# ── Enrichment ───────────────────────────────────────────────────────────

def _enrich_event(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Add date_start, date_end, region, category."""
    today = date.today()
    d_start, d_end = _parse_lehoi_date(ev.get("date_text", ""))
    if not d_start:
        # Fallback: ngày hiện tại + 30 ngày (placeholder)
        from datetime import timedelta
        d_start = today
        d_end = today + timedelta(days=1)
    ev["date_start"] = d_start
    ev["date_end"] = d_end or d_start
    ev["region"] = _classify_region(ev.get("location", ""))
    ev["category"] = _classify_category(ev.get("name", ""), ev.get("description", ""))
    return ev


# ── Top-level ────────────────────────────────────────────────────────────

def scrape_festivals(years: list[int] | None = None) -> list[dict[str, Any]]:
    """Scrape lehoivietnam.com.vn — cả domestic + intl.

    Args:
        years: (compat only, không dùng trong source này vì pagination không
            theo năm). Site list theo page chronological.
    """
    import httpx

    max_domestic = int(os.environ.get("FESTIVAL_MAX_DOMESTIC_PAGES", DEFAULT_MAX_DOMESTIC_PAGES))
    max_intl = int(os.environ.get("FESTIVAL_MAX_INTL_PAGES", DEFAULT_MAX_INTL_PAGES))

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    seen_slugs: set[str] = set()
    out: list[dict[str, Any]] = []

    with httpx.Client(headers=headers, follow_redirects=True, timeout=httpx.Timeout(30.0)) as client:
        # ── Domestic ────────────────────────────────────────────────────
        ok_pages = 0
        empty_pages = 0
        for page in range(1, max_domestic + 1):
            url = f"{LIST_URL_DOMESTIC}?page={page}"
            html = _fetch(url, client)
            if not html:
                logger.warning("[domestic] page %d: fetch fail", page)
                continue
            events = _parse_list_page(html)
            logger.info("[domestic] page %d: %d event", page, len(events))
            if not events:
                empty_pages += 1
                if empty_pages >= 2:
                    logger.info("[domestic] 2 page empty liên tiếp → dừng pagination")
                    break
                continue
            empty_pages = 0
            ok_pages += 1
            for ev in events:
                if ev["slug"] in seen_slugs:
                    continue
                seen_slugs.add(ev["slug"])
                enriched = _enrich_event(ev)
                if enriched:
                    out.append(enriched)
        logger.info("[domestic] xong: %d page OK, %d event", ok_pages, len(out))

        # ── International ───────────────────────────────────────────────
        intl_count_before = len(out)
        empty_pages = 0
        for page in range(1, max_intl + 1):
            url = f"{LIST_URL_INTL}?scope=intl&page={page}"
            html = _fetch(url, client)
            if not html:
                logger.warning("[intl] page %d: fetch fail", page)
                continue
            events = _parse_list_page(html)
            logger.info("[intl] page %d: %d event", page, len(events))
            if not events:
                empty_pages += 1
                if empty_pages >= 2:
                    break
                continue
            empty_pages = 0
            for ev in events:
                # Intl: prefix slug "intl-" để không đụng domestic
                ev["slug"] = f"intl-{ev['slug']}"
                if ev["slug"] in seen_slugs:
                    continue
                seen_slugs.add(ev["slug"])
                enriched = _enrich_event(ev)
                if enriched:
                    out.append(enriched)
        intl_added = len(out) - intl_count_before
        logger.info("[intl] xong: thêm %d event", intl_added)

    logger.info("Festival scrape xong: %d event tổng", len(out))
    return out


# ── Save DB ──────────────────────────────────────────────────────────────

def save_festivals_to_db(db, events: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert events vào DB. Hash-based diff."""
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
    """Top-level: scrape + save."""
    events = scrape_festivals()
    return save_festivals_to_db(db, events)
