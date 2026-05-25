"""
Scrape tour listings from FindTourGo (api-v2) for CN / JP / VN and sync to Google Sheets.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

SOURCE = "FindTourGo"
SHEET_ID = "1sI34D88zsmSrN7Jf9fS3jh4aUvaep-blxnBR1CGq9eM"
GID_FINDTOURGO = 408521834

API_BASE = "https://api-v2.findtourgo.com/v1"
SITE_BASE = "https://findtourgo.com/vi"

# Slug URL theo findtourgo.com (một số quốc gia dùng tên đặc biệt)
COUNTRY_SLUG_OVERRIDE: dict[str, str] = {
    "US": "united-states",
    "GB": "united-kingdom",
    "AE": "united-arab-emirates",
    "KR": "south-korea",
    "LA": "laos",
    "TR": "turkey",
    "VN": "vietnam",
    "CN": "china",
    "JP": "japan",
}

# Cột A–Z (26) — cùng layout tab Vietravel
SHEET_NUM_COLS = 26
COL_LINK_TOUR = 9   # J
COL_MA_TOUR = 12    # M
COL_CAP_NHAT = 13   # N
COL_LINK_RAW = 25   # Z

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

# Mã quốc gia → tên tiếng Việt (cột Lịch trình / điểm đến)
COUNTRY_VI_FALLBACK: dict[str, str] = {
    "CN": "Trung Quốc",
    "JP": "Nhật Bản",
    "VN": "Việt Nam",
    "HK": "Hồng Kông",
    "TW": "Đài Loan",
    "TH": "Thái Lan",
    "KH": "Campuchia",
    "LA": "Lào",
    "MY": "Malaysia",
    "SG": "Singapore",
    "ID": "Indonesia",
    "PH": "Philippines",
    "KR": "Hàn Quốc",
    "US": "Hoa Kỳ",
    "FR": "Pháp",
    "GB": "Anh",
    "AU": "Úc",
    "AE": "Dubai",
}


def _fmt_price(v: int | float | None) -> str:
    if v is None or v == "":
        return "0"
    try:
        n = int(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{n:,}".replace(",", ".")


def _vnd_price(item: dict[str, Any]) -> int:
    sale = item.get("salePrice") or 0
    regular = item.get("regularPrice") or 0
    if sale and sale > 0:
        return int(sale)
    if regular:
        return int(regular)
    for p in item.get("prices") or []:
        if p.get("currency") == "VND":
            sp = p.get("salePrice") or 0
            rp = p.get("regularPrice") or 0
            return int(sp if sp > 0 else rp)
    return 0


def _tour_url(tour_code: str, slug: str) -> str:
    code = (tour_code or "").strip()
    slug = (slug or "").strip()
    if not code:
        return ""
    if slug:
        return f"{SITE_BASE}/tours/{code}/{slug}"
    return f"{SITE_BASE}/tours/{code}"


def _hyperlink_formula(url: str) -> str:
    safe = (url or "").replace('"', '""')
    return f'=HYPERLINK("{safe}";"Xem chi tiết")'


_WEEKDAY_VI: dict[str, str] = {
    "monday": "Thứ 2",
    "tuesday": "Thứ 3",
    "wednesday": "Thứ 4",
    "thursday": "Thứ 5",
    "friday": "Thứ 6",
    "saturday": "Thứ 7",
    "sunday": "Chủ nhật",
    "mon": "Thứ 2",
    "tue": "Thứ 3",
    "wed": "Thứ 4",
    "thu": "Thứ 5",
    "fri": "Thứ 6",
    "sat": "Thứ 7",
    "sun": "Chủ nhật",
}

# Python weekday(): Monday=0 … Sunday=6
_WEEKDAY_NUM: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def _parse_departure_date(val: Any) -> datetime | None:
    """API trả về yyyy-mm-dd (CN/JP) hoặc dd/mm/yyyy (RU, TR, …)."""
    if val is None:
        return None
    if isinstance(val, dict):
        for k in ("date", "departureDate", "startDate", "value"):
            if val.get(k):
                return _parse_departure_date(val[k])
        return None
    text = str(val).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
    return None


def _weekday_label(val: str) -> str:
    key = (val or "").strip().lower()
    return _WEEKDAY_VI.get(key, val)


def _weekday_numbers(weekdays: list[Any]) -> set[int]:
    nums: set[int] = set()
    for w in weekdays:
        key = str(w).strip().lower()
        if key in _WEEKDAY_NUM:
            nums.add(_WEEKDAY_NUM[key])
    return nums


def _schedule_window(
    sch: dict[str, Any], ref_year: int
) -> tuple[datetime | None, datetime | None]:
    """Khoảng ngày áp dụng lịch theo thứ / hàng ngày."""
    start = _parse_departure_date(sch.get("startDate"))
    end = _parse_departure_date(sch.get("endDate"))
    if start and end:
        return start, end
    if start and not end:
        return start, start + timedelta(days=365)
    if end and not start:
        return end - timedelta(days=365), end

    name = (sch.get("scheduleName") or "").strip()
    month = _month_from_schedule_name(name)
    if month:
        import calendar

        last_day = calendar.monthrange(ref_year, month)[1]
        return datetime(ref_year, month, 1), datetime(ref_year, month, last_day)

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    year_end = datetime(ref_year, 12, 31)
    if year_end < today:
        year_end = today + timedelta(days=365)
    return today, year_end


def _expand_weekdays_between(
    start: datetime, end: datetime, weekdays: list[Any]
) -> list[datetime]:
    targets = _weekday_numbers(weekdays)
    if not targets:
        return []
    d0, d1 = start.date(), end.date()
    if d1 < d0:
        d0, d1 = d1, d0
    out: list[datetime] = []
    cur = d0
    while cur <= d1:
        if cur.weekday() in targets:
            out.append(datetime(cur.year, cur.month, cur.day))
        cur += timedelta(days=1)
    return out


def _expand_daily_between(start: datetime, end: datetime) -> list[datetime]:
    d0, d1 = start.date(), end.date()
    if d1 < d0:
        d0, d1 = d1, d0
    out: list[datetime] = []
    cur = d0
    while cur <= d1:
        out.append(datetime(cur.year, cur.month, cur.day))
        cur += timedelta(days=1)
    return out


def _month_from_schedule_name(name: str) -> int | None:
    text = (name or "").strip()
    m = re.search(r"tháng\s*(\d{1,2})", text, flags=re.IGNORECASE)
    if m:
        month = int(m.group(1))
        if 1 <= month <= 12:
            return month
    m = re.search(r"(\d{1,2})[/\-](\d{1,2})", text)
    if m:
        # dd/mm trong tên (vd: 29/04 Lễ 30/4) → lấy tháng từ nhóm thứ hai
        month = int(m.group(2))
        if 1 <= month <= 12:
            return month
    return None


def _dates_from_schedule_name(name: str, year: int) -> list[datetime]:
    """Ngày ghi trong scheduleName, vd: '29/04 (Lễ 30/4)'."""
    found: list[datetime] = []
    for m in re.finditer(r"(\d{1,2})[/\-](\d{1,2})", name or ""):
        day, month = int(m.group(1)), int(m.group(2))
        try:
            found.append(datetime(year, month, day))
        except ValueError:
            continue
    return found


def _collect_schedule_date_values(
    schedules: list[dict[str, Any]],
    year: int | None = None,
) -> tuple[list[datetime], list[str]]:
    """
    Trả về (danh sách ngày cụ thể, nhãn lịch khi API không có ngày cụ thể).
    """
    ref_year = year or datetime.now().year
    found: list[datetime] = []
    labels: list[str] = []

    for sch in schedules:
        dep_type = (sch.get("departureType") or "").upper()
        name = (sch.get("scheduleName") or "").strip()
        weekdays = sch.get("departureWeekdays") or []
        win_start, win_end = _schedule_window(sch, ref_year)

        if dep_type == "DAILY":
            if win_start and win_end:
                found.extend(_expand_daily_between(win_start, win_end))
            else:
                labels.append("Hàng ngày")
            continue

        if dep_type == "RECURRING_WEEKDAYS":
            if isinstance(weekdays, list) and weekdays and win_start and win_end:
                found.extend(_expand_weekdays_between(win_start, win_end, weekdays))
            elif isinstance(weekdays, list) and weekdays:
                labels.append(
                    "Theo thứ: " + ", ".join(_weekday_label(str(w)) for w in weekdays)
                )
            spec = sch.get("departureSpecifiedDates")
            if isinstance(spec, list):
                for item in spec:
                    dt = _parse_departure_date(item)
                    if dt:
                        found.append(dt)
            continue

        if dep_type == "FIXED_DATES":
            month = _month_from_schedule_name(name)
            day_list = sch.get("departureDates") or []
            if month and isinstance(day_list, list):
                for d in day_list:
                    try:
                        day = int(str(d).strip())
                        found.append(datetime(ref_year, month, day))
                    except (TypeError, ValueError):
                        continue
            for key in ("startDate", "endDate"):
                dt = _parse_departure_date(sch.get(key))
                if dt:
                    found.append(dt)
            found.extend(_dates_from_schedule_name(name, ref_year))
            continue

        # FLEXIBLE_DATES và các loại khác
        spec = sch.get("departureSpecifiedDates")
        if isinstance(spec, list):
            for item in spec:
                dt = _parse_departure_date(item)
                if dt:
                    found.append(dt)

        if (
            isinstance(weekdays, list)
            and weekdays
            and dep_type == "FLEXIBLE_DATES"
            and win_start
            and win_end
        ):
            found.extend(_expand_weekdays_between(win_start, win_end, weekdays))

        dep_dates = sch.get("departureDates")
        if isinstance(dep_dates, list) and dep_type != "FIXED_DATES":
            for item in dep_dates:
                dt = _parse_departure_date(item)
                if dt:
                    found.append(dt)

        for key in ("startDate", "endDate"):
            dt = _parse_departure_date(sch.get(key))
            if dt:
                found.append(dt)

        found.extend(_dates_from_schedule_name(name, ref_year))

    return found, labels


def _format_departure_dates(
    schedules: list[dict[str, Any]] | None,
    max_dates: int | None = None,
) -> str:
    """Liệt kê đủ ngày khởi hành (mặc định không cắt bớt)."""
    if not schedules:
        return ""

    parsed, labels = _collect_schedule_date_values(schedules)
    parts: list[str] = []

    if parsed:
        unique = sorted({dt.date() for dt in parsed})
        if max_dates is not None and max_dates > 0:
            shown = unique[:max_dates]
            date_parts = [d.strftime("%d/%m/%Y") for d in shown]
            more = len(unique) - len(shown)
            text = ", ".join(date_parts)
            if more > 0:
                text += f" (+{more} ngày khác)"
        else:
            text = ", ".join(d.strftime("%d/%m/%Y") for d in unique)
        parts.append(text)

    for label in dict.fromkeys(labels):
        if label not in parts:
            parts.append(label)

    return " | ".join(parts)


def _format_duration(item: dict[str, Any]) -> str:
    """Ưu tiên duration API; tên tour chỉ lấy dạng 9N8Đ (không nhầm năm 2025)."""
    days = item.get("duration")
    try:
        d = int(days) if days is not None else 0
    except (TypeError, ValueError):
        d = 0
    if 1 <= d <= 45:
        return f"{d} ngày"

    name = (item.get("name") or "").strip()
    m = re.search(r"(?<!\d)(\d{1,2})\s*[Nn]\s*(\d{1,2})\s*[Đđ]", name)
    if m:
        return f"{m.group(1)}N{m.group(2)}Đ"
    m = re.search(r"(?<!\d)(\d{1,2})\s*[Nn]\b", name)
    if m:
        return f"{m.group(1)}N"
    if 1 <= d <= 90:
        return f"{d} ngày"
    return ""


def _flight_note(item: dict[str, Any]) -> str:
    if (item.get("categoryType") or "") == "FLIGHT_INCLUDED":
        return "Có vé máy bay"
    return ""


def _country_name_vi(code: str, cache: dict[str, str]) -> str:
    code = (code or "").upper()
    if not code:
        return ""
    if code in cache:
        return cache[code]
    return COUNTRY_VI_FALLBACK.get(code, code)


def _load_country_cache(session: requests.Session) -> dict[str, str]:
    cache: dict[str, str] = dict(COUNTRY_VI_FALLBACK)
    try:
        resp = session.get(f"{API_BASE}/public/countries", headers=HEADERS, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return cache
        for row in data:
            code = (row.get("code") or "").upper()
            if not code:
                continue
            vi = ""
            for tr in row.get("nameTranslations") or []:
                lang = (tr.get("language") or tr.get("locale") or "").lower()
                if lang in ("vi", "vn"):
                    vi = (tr.get("value") or "").strip()
                    break
            name = (row.get("name") or "").strip()
            cache[code] = vi or COUNTRY_VI_FALLBACK.get(code, name)
    except Exception:
        pass
    return cache


def _load_city_name(city_id: int | None, cache: dict[int, str], session: requests.Session) -> str:
    if not city_id:
        return ""
    if city_id in cache:
        return cache[city_id]
    try:
        resp = session.get(
            f"{API_BASE}/public/cities/{city_id}",
            params={"locale": "vi"},
            headers=HEADERS,
            timeout=20,
        )
        if resp.ok:
            name = (resp.json().get("name") or "").strip()
            cache[city_id] = name
            return name
    except Exception:
        pass
    cache[city_id] = ""
    return ""


def _resolve_quoc_gia(
    item: dict[str, Any],
    listing_label: str,
    country_cache: dict[str, str],
) -> str:
    dests = item.get("destinationCountries") or []
    if dests:
        names = [_country_name_vi(c, country_cache) for c in dests if c]
        names = [n for n in names if n]
        if names:
            return " - ".join(dict.fromkeys(names))
    return listing_label


def _item_to_row(
    item: dict[str, Any],
    listing_label: str,
    country_cache: dict[str, str],
    city_cache: dict[int, str],
    session: requests.Session,
) -> dict[str, Any]:
    agency = item.get("travelAgency") or {}
    company = (agency.get("name") or "").strip()
    tour_code = (item.get("tourCode") or "").strip()
    slug = (item.get("slug") or "").strip()
    name = (item.get("name") or "").strip()
    url = _tour_url(tour_code, slug)
    dep_city = _load_city_name(item.get("departureCity"), city_cache, session)
    lich_trinh = _resolve_quoc_gia(item, listing_label, country_cache)
    price = _vnd_price(item)
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    return {
        "cong_ty": company,
        "thi_truong": "",
        "tuyen_tour": "",
        "ten_tour": name,
        "lich_trinh": lich_trinh,
        "diem_kh": dep_city,
        "thoi_gian": _format_duration(item),
        "gia": _fmt_price(price),
        "lich_kh": _format_departure_dates(item.get("tourSchedules")),
        "link_tour": _hyperlink_formula(url),
        "link_url": url,
        "ma_tour": tour_code,
        "cap_nhat": now,
        "khach_san": "",
        "hang_khong": _flight_note(item),
    }


def _country_page_url(code: str, slug: str | None = None) -> str:
    slug = slug or COUNTRY_SLUG_OVERRIDE.get(code) or (code or "").lower()
    return f"{SITE_BASE}/country/{slug}?currency=VND"


def list_countries_with_tours(session: requests.Session | None = None) -> list[dict[str, str]]:
    """Danh sách mã quốc gia có ít nhất 1 tour trên FindTourGo."""
    sess = session or requests.Session()
    country_cache = _load_country_cache(sess)
    active: list[dict[str, str]] = []

    resp = sess.get(f"{API_BASE}/public/countries", headers=HEADERS, timeout=90)
    resp.raise_for_status()
    countries = resp.json()
    if not isinstance(countries, list):
        return active

    for row in countries:
        code = (row.get("code") or "").upper()
        if not code:
            continue
        try:
            probe = fetch_country_tours(code, session=sess, page_size=1, max_pages=1)
        except Exception:
            continue
        if not probe:
            continue
        label = _country_name_vi(code, country_cache)
        slug = COUNTRY_SLUG_OVERRIDE.get(code) or (row.get("name") or code).lower()
        slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")
        active.append(
            {
                "code": code,
                "label_vi": label,
                "page_url": _country_page_url(code, slug),
            }
        )
    return active


def fetch_country_tours(
    country_code: str,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_pages: int = 50,
) -> list[dict[str, Any]]:
    """Lấy toàn bộ tour một quốc gia (phân trang theo canNext)."""
    sess = session or requests.Session()
    items: list[dict[str, Any]] = []
    page = 0
    while page < max_pages:
        resp = sess.get(
            f"{API_BASE}/search/tours",
            params={
                "countryCode": country_code,
                "page": page,
                "pageSize": page_size,
                "locale": "vi",
                "currency": "VND",
            },
            headers=HEADERS,
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("items") or []
        if not batch:
            break
        items.extend(batch)
        if not data.get("canNext"):
            break
        page += 1
    return items


def scrape_all_findtourgo_tours(
    country_codes: list[str] | None = None,
) -> pd.DataFrame:
    """Quét tour theo từng quốc gia trên FindTourGo; mặc định tất cả quốc gia có tour."""
    sess = requests.Session()
    country_cache = _load_country_cache(sess)
    city_cache: dict[int, str] = {}
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    if country_codes:
        sources = [
            {
                "code": c.upper(),
                "label_vi": _country_name_vi(c.upper(), country_cache),
                "page_url": _country_page_url(c.upper()),
            }
            for c in country_codes
        ]
    else:
        resp = sess.get(f"{API_BASE}/public/countries", headers=HEADERS, timeout=90)
        resp.raise_for_status()
        payload = resp.json()
        all_countries = payload if isinstance(payload, list) else []
        sources = []
        for row in all_countries:
            code = (row.get("code") or "").upper()
            if not code:
                continue
            en_name = (row.get("name") or code).lower()
            slug = COUNTRY_SLUG_OVERRIDE.get(code) or re.sub(
                r"[^a-z0-9]+", "-", en_name
            ).strip("-")
            sources.append(
                {
                    "code": code,
                    "label_vi": _country_name_vi(code, country_cache),
                    "page_url": _country_page_url(code, slug),
                }
            )

    for src in sources:
        code = src["code"]
        label = src["label_vi"]
        page_url = src["page_url"]
        raw_items = fetch_country_tours(code, session=sess)
        for item in raw_items:
            tour_code = (item.get("tourCode") or "").strip()
            if tour_code and tour_code in seen_codes:
                continue
            if tour_code:
                seen_codes.add(tour_code)
            row = _item_to_row(item, label, country_cache, city_cache, sess)
            row["page_url"] = page_url
            row["listing_code"] = code
            rows.append(row)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    from vietravel_scraper import enrich_market_and_route

    return enrich_market_and_route(df)


def _sheet_headers() -> list[str]:
    headers = [""] * SHEET_NUM_COLS
    headers[0] = "Tên Công Ty"
    headers[1] = "Thị trường"
    headers[2] = "Tuyến tour"
    headers[3] = "Tên Tour"
    headers[4] = "Lịch trình"
    headers[5] = "Điểm khởi hành"
    headers[6] = "Thời gian"
    headers[7] = "Giá"
    headers[8] = "Lịch khởi hành"
    headers[COL_LINK_TOUR] = "Link tour"
    headers[10] = "Khách sạn"
    headers[11] = "Hàng không"
    headers[COL_MA_TOUR] = "Mã tour"
    headers[COL_CAP_NHAT] = "Cập nhật"
    headers[COL_LINK_RAW] = "Link"
    return headers


def tours_to_sheet_rows(df: pd.DataFrame) -> list[list[str]]:
    """Map scraped data to columns A–Z (link thô ở cột Z)."""
    rows = [_sheet_headers()]
    for _, r in df.iterrows():
        row = [""] * SHEET_NUM_COLS
        row[0] = str(r.get("cong_ty", ""))
        row[1] = str(r.get("thi_truong", ""))
        row[2] = str(r.get("tuyen_tour", ""))
        row[3] = str(r.get("ten_tour", ""))
        row[4] = str(r.get("lich_trinh", ""))
        row[5] = str(r.get("diem_kh", ""))
        row[6] = str(r.get("thoi_gian", ""))
        row[7] = str(r.get("gia", ""))
        row[8] = str(r.get("lich_kh", ""))
        row[COL_LINK_TOUR] = str(r.get("link_tour", ""))
        row[10] = str(r.get("khach_san", ""))
        row[11] = str(r.get("hang_khong", ""))
        row[COL_MA_TOUR] = str(r.get("ma_tour", ""))
        row[COL_CAP_NHAT] = str(r.get("cap_nhat", ""))
        row[COL_LINK_RAW] = str(r.get("link_url", ""))
        rows.append(row)
    return rows


def _get_gspread_client():
    from google_auth import get_gspread_client
    return get_gspread_client()


def _read_existing_rows(ws) -> list[list[str]]:
    try:
        vals = ws.get_all_values()
        return vals if vals else []
    except Exception:
        return []


def _merge_sheet_rows(
    existing: list[list[str]],
    new_rows: list[list[str]],
    scraped_codes: set[str],
) -> list[list[str]]:
    """
    Giữ tour các thị trường khác trên sheet; cập nhật tour trùng mã VN-* từ lần quét mới.
    """
    if not existing:
        return new_rows

    header = new_rows[0]
    out = [header]
    code_col = COL_MA_TOUR

    for row in existing[1:]:
        padded = row + [""] * (SHEET_NUM_COLS - len(row))
        padded = padded[:SHEET_NUM_COLS]
        if len(padded) <= code_col:
            out.append(padded)
            continue
        code = (padded[code_col] or "").strip()
        if code and code in scraped_codes:
            continue
        out.append(padded)

    out.extend(new_rows[1:])
    return out


def write_to_google_sheet(
    df: pd.DataFrame,
    gid: int = GID_FINDTOURGO,
    merge_existing: bool = False,
) -> dict[str, Any]:
    """Ghi tab FindTourGo; mặc định ghi đè toàn bộ tab sau khi quét đủ quốc gia."""
    import gspread

    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet_by_id(gid)
    if ws is None:
        raise ValueError(f"Không tìm thấy sheet gid={gid}")

    new_rows = tours_to_sheet_rows(df)
    code_key = "ma_tour" if "ma_tour" in df.columns else "page_code"
    scraped_codes = {str(c).strip() for c in df[code_key].dropna() if str(c).strip()}

    if merge_existing:
        existing = _read_existing_rows(ws)
        rows = _merge_sheet_rows(existing, new_rows, scraped_codes)
    else:
        rows = new_rows

    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")

    return {
        "sheet_title": ws.title,
        "rows_written": len(rows) - 1,
        "rows_scraped": len(df),
        "merged": merge_existing,
        "gid": gid,
        "companies": int(df["cong_ty"].nunique()) if "cong_ty" in df.columns else 0,
    }


def sync_findtourgo_to_sheet(merge_existing: bool = False) -> dict[str, Any]:
    """Pipeline: quét toàn bộ quốc gia FindTourGo → ghi Google Sheet."""
    df = scrape_all_findtourgo_tours()
    if df.empty:
        raise RuntimeError("Không quét được tour nào từ FindTourGo API")
    meta = write_to_google_sheet(df, merge_existing=merge_existing)
    meta["tours_scraped"] = len(df)
    meta["markets"] = int(df["thi_truong"].nunique())
    meta["routes"] = int(df["tuyen_tour"].nunique())
    return meta
