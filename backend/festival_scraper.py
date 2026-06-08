"""Scrape lehoivietnam.com.vn JSON API — Sự kiện & Lễ hội VN (Final).

PHÁT HIỆN QUAN TRỌNG: site có JSON API public!

  Endpoint: GET /api/events?page=N
  Response: { meta: {page, per_page, total, page_count}, items: [...] }
  Total: 2,953 events nội địa, 148 pages × 20 per page.

Mỗi item có structured fields:
  - id, title, slug, url
  - image_url, start_date (ISO), end_date (ISO), date_text, date_span_text
  - loc2 {id, name}: province  (vd "T. Ninh Bình")
  - loc3 {id, name}: commune    (vd "P. Tam Chúc")
  - location_text: combined     (vd "P. Tam Chúc, T. Ninh Bình")
  - summary_short, highlights, tags_grouped

KHÔNG cần parse HTML/markdown nữa! Direct httpx → JSON → save DB.

Tần suất: weekly cron (data ít đổi). Default scrape 30 page domestic (~600
events). Configurable qua env vars.
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
API_URL = f"{BASE_URL}/api/events"
# Tăng từ 30 → 75 pages = 1,500 events. Bao phủ cả domestic + intl events.
# Intl events nằm interleaved trong dataset, classify qua loc2.name (không
# có prefix "T."/"TP." → intl). Full dataset = 148 pages = 2,953 events.
DEFAULT_MAX_PAGES = 75

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SEC = 30.0
RATE_LIMIT_SEC = 0.5  # API thường rate-limit thoải mái hơn HTML


# ── Province + region map (VN) ───────────────────────────────────────────

# Tên tỉnh thật trong loc2.name có prefix "T." (Tỉnh) hoặc "TP." (Thành phố).
# Vd "T. Ninh Bình", "TP. Hà Nội", "TP. Đà Nẵng".
_REGION_BY_PROVINCE_KEYWORD: dict[str, str] = {
    # Bắc Bộ
    "hà nội": "bac", "ha noi": "bac", "hanoi": "bac",
    "hải phòng": "bac", "hai phong": "bac",
    "quảng ninh": "bac", "quang ninh": "bac",
    "lào cai": "bac", "lao cai": "bac",
    "ninh bình": "bac", "ninh binh": "bac",
    "hà giang": "bac", "ha giang": "bac",
    "thái nguyên": "bac", "thai nguyen": "bac",
    "bắc ninh": "bac", "bac ninh": "bac",
    "phú thọ": "bac", "phu tho": "bac",
    "yên bái": "bac", "yen bai": "bac",
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
    "quảng bình": "trung", "quang binh": "trung",
    "quảng trị": "trung", "quang tri": "trung",
    "khánh hòa": "trung", "khanh hoa": "trung", "nha trang": "trung",
    "phú yên": "trung", "phu yen": "trung",
    "bình định": "trung", "binh dinh": "trung",
    "ninh thuận": "trung", "ninh thuan": "trung",
    "bình thuận": "trung", "binh thuan": "trung",
    "đà lạt": "trung", "da lat": "trung", "lâm đồng": "trung", "lam dong": "trung",
    "kon tum": "trung",
    "gia lai": "trung",
    "đắk lắk": "trung", "dak lak": "trung",
    "đắk nông": "trung", "dak nong": "trung",
    "quảng ngãi": "trung", "quang ngai": "trung",
    "hà tĩnh": "trung", "ha tinh": "trung",
    # Nam Bộ
    "tp.hcm": "nam", "tphcm": "nam", "tp hcm": "nam",
    "hồ chí minh": "nam", "ho chi minh": "nam",
    "sài gòn": "nam", "saigon": "nam",
    "cần thơ": "nam", "can tho": "nam",
    "vũng tàu": "nam", "vung tau": "nam", "bà rịa": "nam", "ba ria": "nam",
    "đồng nai": "nam", "dong nai": "nam",
    "bình dương": "nam", "binh duong": "nam",
    "long an": "nam",
    "tiền giang": "nam", "tien giang": "nam",
    "bến tre": "nam", "ben tre": "nam",
    "vĩnh long": "nam", "vinh long": "nam",
    "an giang": "nam",
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


# Intl country keywords — classify event là intl khi loc2.name không có prefix VN.
_INTL_COUNTRY_KEYWORDS = {
    "hàn quốc", "han quoc", "korea", "south korea", "kr",
    "nhật bản", "nhat ban", "japan", "jp",
    "trung quốc", "trung quoc", "china", "cn",
    "thái lan", "thai lan", "thailand", "th",
    "lào", "lao", "laos",
    "campuchia", "cambodia", "kh",
    "singapore", "sg",
    "malaysia", "my",
    "indonesia", "id",
    "philippines", "ph",
    "đài loan", "dai loan", "taiwan", "tw",
    "ấn độ", "an do", "india", "in",
    "úc", "uc", "australia", "au",
    "mỹ", "my", "usa", "united states", "america", "us",
    "anh", "uk", "england", "britain", "united kingdom",
    "pháp", "phap", "france", "fr",
    "đức", "duc", "germany", "de",
    "ý", "italy", "italia", "it",
    "tây ban nha", "spain", "es",
    "nga", "russia", "ru",
    "canada", "ca",
    "brazil", "br",
    "thụy điển", "sweden", "se",
    "thụy sĩ", "switzerland", "ch",
    "hà lan", "ha lan", "netherlands", "nl",
    "bỉ", "belgium", "be",
    "áo", "austria", "at",
    "ba lan", "poland", "pl",
}


def _classify_region(location_text: str) -> str:
    """Region: bac/trung/nam cho VN; 'intl' cho quốc tế."""
    if not location_text:
        return ""
    lt = location_text.lower()
    # Check VN province trước (cụ thể hơn)
    for kw, region in _REGION_BY_PROVINCE_KEYWORD.items():
        if kw in lt:
            return region
    # Check intl country
    for kw in _INTL_COUNTRY_KEYWORDS:
        if kw in lt:
            return "intl"
    return ""


def _is_intl_event(item: dict) -> bool:
    """Detect intl event qua loc2.name pattern.

    Domestic VN: "T. Ninh Bình", "TP. Hà Nội", "TP. Đà Nẵng" (có prefix "T."/"TP.")
    Intl:       "Hàn Quốc", "Nhật Bản", "USA" (không có prefix)
    """
    loc2 = item.get("loc2") or {}
    name = (loc2.get("name") if isinstance(loc2, dict) else "") or ""
    if not name:
        return False
    name_clean = name.strip().lower()
    # Có prefix VN → domestic
    if name_clean.startswith(("t.", "tp.", "t ", "tp ")):
        return False
    # Khác có thể intl — verify bằng keyword
    for kw in _INTL_COUNTRY_KEYWORDS:
        if kw in name_clean:
            return True
    return False


# Category map từ tags_grouped (nếu API trả) hoặc heuristic
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "religious": ["chùa", "đền", "phật", "lễ phật", "lễ chùa", "vu lan", "phật đản",
                  "tâm linh", "lễ tế", "đình", "lễ giỗ"],
    "music":     ["âm nhạc", "festival music", "concert", "ca trù", "quan họ",
                  "đờn ca", "music", "biểu diễn"],
    "food":      ["ẩm thực", "food", "trà", "cà phê", "ocop", "sầu riêng",
                  "vải", "đặc sản", "ngon"],
    "sport":     ["thể thao", "marathon", "đua", "chọi trâu", "đua ghe",
                  "đua thuyền", "ironman", "thi đấu"],
    "cultural":  ["lễ hội", "truyền thống", "văn hóa", "dân gian", "cổ truyền",
                  "hội", "festival", "carnival", "liên hoan", "triển lãm"],
}


def _classify_category_from_item(item: dict) -> str:
    """Classify từ tags_grouped (nếu có) hoặc title+summary.

    Defensive: tags_grouped có thể là dict hoặc list, item có thể là dict
    với name=None, hoặc string. Mọi nhánh đều check None trước khi .lower().
    """
    # API trả tags_grouped có category section
    tags_grouped = item.get("tags_grouped") or {}
    if isinstance(tags_grouped, dict):
        category_tags = tags_grouped.get("category") or []
    else:
        category_tags = []
    if category_tags and isinstance(category_tags, list):
        # Lấy tag đầu tiên làm category
        first = category_tags[0]
        raw_name = ""
        if isinstance(first, dict):
            raw_name = first.get("name") or ""
        elif isinstance(first, str):
            raw_name = first
        tag_name = (raw_name or "").lower()
        if tag_name:
            if "lễ hội" in tag_name or "truyền thống" in tag_name:
                return "cultural"
            if "ẩm thực" in tag_name or "food" in tag_name:
                return "food"
            if "tâm linh" in tag_name or "tôn giáo" in tag_name:
                return "religious"
            if "âm nhạc" in tag_name or "music" in tag_name:
                return "music"
            if "thể thao" in tag_name or "sport" in tag_name:
                return "sport"
    # Fallback heuristic từ title + summary
    text = ((item.get("title") or "") + " " + (item.get("summary_short") or "")).lower()
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


def _compute_hash(*parts: str) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update((p or "").encode("utf-8"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _parse_iso_date(s: str) -> date | None:
    """Parse "2026-08-15" → date object. None nếu invalid."""
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        # Thử format khác
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
        except Exception:  # noqa: BLE001
            return None


def _full_url(path_or_url: str) -> str:
    """Ensure URL absolute. Empty → empty."""
    if not path_or_url:
        return ""
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if path_or_url.startswith("//"):
        return "https:" + path_or_url
    if path_or_url.startswith("/"):
        return urljoin(BASE_URL, path_or_url)
    return path_or_url


def _build_event_from_api_item(item: dict) -> dict[str, Any] | None:
    """Convert 1 API item → festival event dict cho save_festivals_to_db."""
    slug_raw = (item.get("slug") or "").strip()
    title = (item.get("title") or "").strip()
    if not slug_raw or not title:
        return None
    # Slug: ưu tiên dùng id-prefix nếu có (đảm bảo unique)
    item_id = item.get("id")
    if item_id:
        slug = f"lhv-{item_id}-{slug_raw[:200]}"
    else:
        slug = f"lhv-{slug_raw[:240]}"

    d_start = _parse_iso_date(item.get("start_date", ""))
    d_end = _parse_iso_date(item.get("end_date", ""))
    if not d_start:
        # Skip event không có ngày bắt đầu (không hiện được trên timeline)
        return None
    if not d_end:
        d_end = d_start

    # Location: ưu tiên location_text, fallback loc2.name
    location_text = (item.get("location_text") or "").strip()
    if not location_text:
        loc2 = item.get("loc2") or {}
        location_text = (loc2.get("name") if isinstance(loc2, dict) else "") or ""

    description = (item.get("summary_short") or "").strip()
    # Highlights: gộp vào description nếu có
    highlights = item.get("highlights") or []
    if highlights and isinstance(highlights, list):
        bullets = "\n• " + "\n• ".join(str(h).strip() for h in highlights if h)
        if description:
            description += "\n\nĐiểm nhấn:" + bullets
        else:
            description = "Điểm nhấn:" + bullets

    image_url = _full_url(item.get("image_url", ""))
    source_url = _full_url(item.get("url", ""))

    return {
        "slug": slug,
        "name": title[:512],
        "date_text": item.get("date_text", ""),
        "date_start": d_start,
        "date_end": d_end,
        "location": location_text[:256],
        "description": description[:4000],
        "image_url": image_url[:1024],
        "source_url": source_url[:1024],
        "region": _classify_region(location_text),
        "category": _classify_category_from_item(item),
    }


# ── Fetch JSON ───────────────────────────────────────────────────────────


def _fetch_json_page(url: str, client) -> dict | None:
    """GET JSON. Trả dict hoặc None nếu fail."""
    try:
        r = client.get(url, timeout=REQUEST_TIMEOUT_SEC)
        if r.status_code != 200:
            logger.warning("API HTTP %d: %s", r.status_code, r.text[:200])
            return None
        return r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("API fetch lỗi: %s", e)
        return None


def scrape_festivals(years: list[int] | None = None) -> list[dict[str, Any]]:
    """Scrape lehoivietnam.com.vn JSON API.

    Args:
        years: (compat only — API trả tất cả events theo pagination chronological,
               không filter theo năm).
    """
    import httpx

    max_pages = int(os.environ.get("FESTIVAL_MAX_PAGES", DEFAULT_MAX_PAGES))

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }

    seen_slugs: set[str] = set()
    out: list[dict[str, Any]] = []
    intl_count = 0
    domestic_count = 0

    with httpx.Client(headers=headers, follow_redirects=True, timeout=REQUEST_TIMEOUT_SEC) as client:
        total_pages = None
        for page in range(1, max_pages + 1):
            url = f"{API_URL}?page={page}"
            data = _fetch_json_page(url, client)
            if not data:
                logger.warning("Page %d: fetch fail", page)
                if page >= 3:
                    break
                continue

            meta = data.get("meta") or {}
            if total_pages is None:
                total_pages = meta.get("page_count")
                total_events = meta.get("total")
                logger.info("API meta: %d events / %d pages", total_events or 0, total_pages or 0)

            items = data.get("items") or []
            if not items:
                logger.info("Page %d empty → dừng pagination", page)
                break

            added_this_page = 0
            page_intl = 0
            for item in items:
                ev = _build_event_from_api_item(item)
                if not ev:
                    continue
                if ev["slug"] in seen_slugs:
                    continue
                seen_slugs.add(ev["slug"])
                # Mark intl events: prefix slug + override region
                if _is_intl_event(item):
                    ev["slug"] = f"intl-{ev['slug']}"
                    ev["region"] = "intl"
                    intl_count += 1
                    page_intl += 1
                else:
                    domestic_count += 1
                out.append(ev)
                added_this_page += 1
            logger.info(
                "Page %d: %d items → +%d (intl=%d, domestic=%d, tổng=%d)",
                page, len(items), added_this_page, page_intl, added_this_page - page_intl, len(out),
            )

            if total_pages and page >= total_pages:
                break

            time.sleep(RATE_LIMIT_SEC)

    logger.info(
        "Festival API scrape xong: %d event tổng (domestic=%d, intl=%d)",
        len(out), domestic_count, intl_count,
    )
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
