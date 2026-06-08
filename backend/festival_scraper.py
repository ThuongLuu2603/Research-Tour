"""Scrape vietnam.travel/event — Sự kiện & Lễ hội VN.

Stack: httpx (sync) + selectolax (CSS parser ~5x BeautifulSoup).
KHÔNG cần Playwright — vietnam.travel render server-side (Drupal CMS).

Tần suất: weekly cron (lễ hội ít đổi). Crawl 2 năm × 12 tháng = 24 list page.
Detail page chỉ fetch khi slug mới hoặc hash thay đổi.

Rate limit: 1 req/giây + User-Agent rõ ràng (tôn trọng nguồn).
"""
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
EVENT_LIST_URL = f"{BASE_URL}/things-to-do/festival-event"
USER_AGENT = (
    "VietravelOTA-FestivalBot/1.0 (research; respects robots.txt; "
    "contact via vietravel.com)"
)
RATE_LIMIT_SEC = 1.0
REQUEST_TIMEOUT_SEC = 30.0

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


def _parse_date_range(text: str) -> tuple[date | None, date | None]:
    """Parse các format ngày phổ biến vietnam.travel:
        "5 - 7 Jun, 2026"
        "Jun 15, 2026"
        "2026-06-05 to 2026-06-07"
    Trả (start, end). Nếu chỉ 1 ngày → start == end.
    """
    if not text:
        return None, None
    t = text.strip()
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
    # Format "5 - 7 Jun, 2026"
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
    # Format "Jun 15, 2026" hoặc "15 Jun 2026"
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
    return None, None


def _month_to_num(s: str) -> int | None:
    s = s.lower().strip()[:3]
    for i, name in enumerate(_MONTH_SLUG, start=1):
        if name == s:
            return i
    return None


def _fetch(url: str, client) -> str | None:
    """GET URL với rate limit + retry 1 lần. Trả HTML hoặc None nếu fail."""
    try:
        r = client.get(url, timeout=REQUEST_TIMEOUT_SEC)
        if r.status_code != 200:
            logger.warning("Festival fetch %s -> HTTP %d", url, r.status_code)
            return None
        return r.text
    except Exception as e:  # noqa: BLE001
        logger.warning("Festival fetch %s lỗi: %s", url, e)
        return None
    finally:
        time.sleep(RATE_LIMIT_SEC)


def _parse_list_page(html: str) -> list[dict[str, Any]]:
    """Parse trang danh sách event → list dict {slug, name, date_text, location, image, url}.

    Cấu trúc HTML vietnam.travel (Drupal): mỗi event nằm trong card. Selector
    có thể đổi theo theme update — wrap trong try và log nếu parse fail nhiều.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    events: list[dict[str, Any]] = []

    # Card selector — Drupal node teaser, có thể là article.node hoặc div.event-card
    # Thử nhiều selector và lấy cái nào có kết quả
    selectors = [
        "article.node--type-event",
        "div.event-card",
        "article.event-teaser",
        "div.views-row article",
        "div.views-row",
    ]
    cards = []
    for sel in selectors:
        cards = tree.css(sel)
        if cards:
            break

    for card in cards:
        try:
            # Title + URL
            title_node = (
                card.css_first("h2 a")
                or card.css_first("h3 a")
                or card.css_first(".event-title a")
                or card.css_first("a.event-link")
            )
            if not title_node:
                continue
            name = (title_node.text() or "").strip()
            href = title_node.attributes.get("href", "")
            if not name or not href:
                continue
            url = urljoin(BASE_URL, href)
            slug = href.rstrip("/").split("/")[-1] or _slugify(name)

            # Date text
            date_node = (
                card.css_first(".event-date")
                or card.css_first(".field--name-field-event-date")
                or card.css_first("time")
            )
            date_text = (date_node.text() or "").strip() if date_node else ""

            # Location
            loc_node = (
                card.css_first(".event-location")
                or card.css_first(".field--name-field-location")
            )
            location_text = (loc_node.text() or "").strip() if loc_node else ""

            # Image
            img_node = card.css_first("img")
            image_url = ""
            if img_node:
                src = img_node.attributes.get("src") or img_node.attributes.get("data-src", "")
                if src:
                    image_url = urljoin(BASE_URL, src)

            events.append({
                "slug": slug,
                "name": name,
                "date_text": date_text,
                "location": location_text,
                "image_url": image_url,
                "source_url": url,
            })
        except Exception as e:  # noqa: BLE001
            logger.debug("Parse 1 card lỗi: %s", e)
            continue

    return events


def _parse_detail_page(html: str) -> dict[str, str]:
    """Parse trang detail → description chi tiết (Phase 1 chỉ lấy mô tả)."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    desc_node = (
        tree.css_first("div.field--name-body")
        or tree.css_first("div.event-description")
        or tree.css_first("article .content")
    )
    description = (desc_node.text(separator=" ", strip=True) if desc_node else "")
    return {"description": description[:4000]}


def scrape_festivals(years: list[int] | None = None) -> list[dict[str, Any]]:
    """Crawl vietnam.travel/event cho mỗi (year, month) trong years × 12.

    Args:
        years: list năm cần crawl. Default = [current_year, current_year+1].

    Returns:
        List dict event đầy đủ fields (chưa save DB).
    """
    import httpx

    today = datetime.now()
    if years is None:
        years = [today.year, today.year + 1]

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "vi,en;q=0.9"}
    seen_slugs: set[str] = set()
    out: list[dict[str, Any]] = []

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        for year in years:
            for month_idx, month_slug in enumerate(_MONTH_SLUG, start=1):
                url = f"{EVENT_LIST_URL}?month={month_slug}&year={year}"
                logger.info("Crawl festival list %s", url)
                html = _fetch(url, client)
                if not html:
                    continue
                events = _parse_list_page(html)
                for ev in events:
                    if ev["slug"] in seen_slugs:
                        continue
                    seen_slugs.add(ev["slug"])

                    # Parse date range
                    d_start, d_end = _parse_date_range(ev["date_text"])
                    # Fallback: chấp nhận năm + tháng đang crawl
                    if not d_start:
                        try:
                            d_start = date(year, month_idx, 1)
                            d_end = d_start
                        except ValueError:
                            continue

                    ev["date_start"] = d_start
                    ev["date_end"] = d_end or d_start
                    ev["region"] = _classify_region(ev["location"])
                    ev["category"] = _classify_category(ev["name"])

                    # Fetch detail page cho description (best effort)
                    detail_html = _fetch(ev["source_url"], client)
                    if detail_html:
                        try:
                            detail = _parse_detail_page(detail_html)
                            ev["description"] = detail.get("description", "")
                        except Exception as e:  # noqa: BLE001
                            logger.debug("Detail parse lỗi %s: %s", ev["source_url"], e)
                            ev["description"] = ""
                    else:
                        ev["description"] = ""

                    out.append(ev)

    logger.info("Festival scrape xong: %d event (qua %d năm)", len(out), len(years))
    return out


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
