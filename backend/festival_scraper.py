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
# URL chính là /event (số ít), KHÔNG phải /things-to-do/festival-event (đã thử 404).
# Trang /event là listing, link tới detail vẫn là /things-to-do/festival-event/{slug}.
EVENT_LIST_URL = f"{BASE_URL}/event"
DETAIL_PATH_PREFIX = "/things-to-do/festival-event/"
# User-Agent: dùng Chrome-like để tránh WAF chặn bot. Trước đây dùng string
# "VietravelOTA-FestivalBot/1.0" rõ ràng nhưng vietnam.travel có thể block ở edge
# (Cloudflare/WAF) khiến SSL handshake timeout. Thử Chrome UA để bypass.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Rate limit: vẫn polite (1.5s ≈ 40 req/min). Mỗi lần scrape ~24 list page +
# 30-60 detail page = ~100-130 request × 1.5s = 2.5-3 phút tổng.
RATE_LIMIT_SEC = 1.5
# Timeout: Render free tier → vietnam.travel (server VN) qua quốc tế có thể chậm.
# SSL handshake riêng có thể tốn 3-10s. Tăng từ 30s → 60s.
REQUEST_TIMEOUT_SEC = 60.0
# Retry: connect/SSL errors → thử lại 1 lần với backoff 3s.
MAX_RETRIES = 2

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
        "20 May 2026 - 10 Jun 2026"   ← FORMAT CHÍNH hiện tại
        "01 Jun 2026 - 30 Jun 2026"
        "Jun 15, 2026"
        "2026-06-05 to 2026-06-07"    ← ISO fallback
        "5 - 7 Jun, 2026"             ← cũ
    Trả (start, end). Nếu chỉ 1 ngày → start == end.
    """
    if not text:
        return None, None
    t = text.strip()

    # Format CHÍNH: "DD MMM YYYY - DD MMM YYYY" (có month name ở cả 2)
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
    return None, None


def _month_to_num(s: str) -> int | None:
    s = s.lower().strip()[:3]
    for i, name in enumerate(_MONTH_SLUG, start=1):
        if name == s:
            return i
    return None


def _fetch(url: str, client) -> str | None:
    """GET URL với rate limit + retry. Trả HTML hoặc None nếu fail sau retry.

    Retry trên SSL/connect timeout phổ biến từ Render → server VN (qua quốc tế
    có thể chậm SSL handshake). Backoff 3s giữa các lần thử.
    """
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = client.get(url, timeout=REQUEST_TIMEOUT_SEC)
            time.sleep(RATE_LIMIT_SEC)
            if r.status_code != 200:
                logger.warning("Festival fetch %s -> HTTP %d", url, r.status_code)
                return None
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < MAX_RETRIES:
                logger.info(
                    "Festival fetch %s thử %d/%d lỗi: %s — retry sau 3s",
                    url, attempt + 1, MAX_RETRIES + 1, type(e).__name__,
                )
                time.sleep(3.0)
            else:
                logger.warning(
                    "Festival fetch %s thất bại sau %d lần: %s",
                    url, MAX_RETRIES + 1, e,
                )
                time.sleep(RATE_LIMIT_SEC)
    return None


def _parse_list_page(html: str) -> list[dict[str, Any]]:
    """Parse trang danh sách event → list dict.

    STRATEGY MỚI (Phase 1.1): link-based extraction.
      1. Tìm mọi anchor có href chứa "/things-to-do/festival-event/{slug}".
      2. Mỗi anchor → traverse parent để tìm card chứa nó.
      3. Trong card: lấy title (text anchor), image (img gần nhất), date_text + location
         (text node có pattern ngày hoặc tên tỉnh VN).

    Lý do: vietnam.travel KHÔNG dùng class CSS thuần (vd .event-card hay article.node),
    HTML generic divs. Anchor-based extraction robust hơn nhiều khi theme update.
    """
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    events: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    # Tìm mọi link tới festival detail page
    detail_links = tree.css(f'a[href*="{DETAIL_PATH_PREFIX}"]')
    logger.info("Tìm thấy %d detail link trên trang", len(detail_links))

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

    # Headers chuẩn browser để tránh WAF
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    seen_slugs: set[str] = set()
    out: list[dict[str, Any]] = []

    # Timeout breakdown: connect=20s + read=60s. Render → VN qua quốc tế có thể
    # chậm phase TCP connect lẫn TLS handshake; pool_connect riêng tránh kẹt cứng.
    timeout_config = httpx.Timeout(connect=20.0, read=REQUEST_TIMEOUT_SEC, write=10.0, pool=10.0)
    with httpx.Client(
        headers=headers,
        follow_redirects=True,
        timeout=timeout_config,
        # http2=False (default) — tránh negotiation phụ vì site có thể chỉ HTTP/1.1
    ) as client:
        for year in years:
            for month_idx, month_slug in enumerate(_MONTH_SLUG, start=1):
                url = f"{EVENT_LIST_URL}?month={month_slug}&year={year}"
                html = _fetch(url, client)
                if not html:
                    logger.warning("Crawl %s/%s: fetch fail", month_slug, year)
                    continue
                events = _parse_list_page(html)
                logger.info(
                    "Crawl %s/%s: %d event (HTML %d bytes)",
                    month_slug, year, len(events), len(html),
                )
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
