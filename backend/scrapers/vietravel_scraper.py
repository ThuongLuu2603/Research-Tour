"""
Scrape tour listings from travel.com.vn (Vietravel) and sync to Google Sheets.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd
import requests

COMPANY = "Vietravel"
SHEET_ID = "1sI34D88zsmSrN7Jf9fS3jh4aUvaep-blxnBR1CGq9eM"
GID_VIETRAVEL = 620817544

SOURCES = [
    "https://travel.com.vn/du-lich-viet-nam.aspx",
    "https://travel.com.vn/du-lich-nuoc-ngoai.aspx",
]

# Cột A–Z (26 cột); Z = link thô cho UI
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
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

# Card header (split chunks start right after \"pageId\":)
_CARD_RE = re.compile(
    r'^(\d+),\\"pageCode\\":\\"([^\\"]+)\\",\\"pageTitle\\":\\"([^\\"]*)\\"'
    r'.*?\\"linkShare\\":\\"(https://travel\.com\.vn/chuong-trinh/[^\\"]+)\\"',
    re.S,
)

_FIELD_RE = {
    "departureName": re.compile(r'\\"departureName\\":\\"([^\\"]*)\\"'),
    "dayStayText": re.compile(r'\\"dayStayText\\":\\"([^\\"]*)\\"'),
    "dayNight": re.compile(r'\\"dayNight\\":\\"([^\\"]*)\\"'),
}


def _field_in_block(block: str, key: str) -> str:
    pat = _FIELD_RE.get(key)
    if not pat:
        return ""
    m = pat.search(block)
    return _decode_json_str(m.group(1)) if m else ""


def _decode_json_str(s: str) -> str:
    """Decode embedded JSON string escapes to UTF-8 text."""
    if not s:
        return ""
    try:
        return json.loads(f'"{s}"')
    except json.JSONDecodeError:
        return (
            s.replace("\\u0026", "&")
            .replace('\\"', '"')
            .replace("\\n", " ")
            .replace("\\t", " ")
        )


def _hyperlink_formula(url: str) -> str:
    """Google Sheets VN dùng dấu ; trong công thức."""
    safe = (url or "").replace('"', '""')
    return f'=HYPERLINK("{safe}";"Xem chi tiết")'


def enrich_market_and_route(df: pd.DataFrame) -> pd.DataFrame:
    """Áp dụng quy tắc Thị trường (keyword) rồi Tuyến tour (sheet Điểm tuyến Tour)."""
    from market_rules import resolve_thi_truong
    from route_rules import load_route_rules, resolve_tuyen_tour

    out = df.copy()
    rules = load_route_rules()
    out["thi_truong"] = out.apply(
        lambda r: resolve_thi_truong(r.get("ten_tour", ""), r.get("lich_trinh", "")),
        axis=1,
    )
    out["tuyen_tour"] = out.apply(
        lambda r: resolve_tuyen_tour(
            r.get("thi_truong", ""),
            r.get("ten_tour", ""),
            r.get("lich_trinh", ""),
            rules,
        ),
        axis=1,
    )
    return out


def _fmt_price(v: int | None) -> str:
    if v is None:
        return ""
    return f"{v:,}".replace(",", ".")


def _extract_schedule(chunk: str, max_len: int = 20000) -> str:
    sub = chunk[:max_len]
    dates = re.findall(r'\\"date\\":\\"(\d{4}-\d{2}-\d{2})', sub)
    if not dates:
        return ""
    unique = sorted(set(dates))[:12]
    parts = []
    for d in unique:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            parts.append(dt.strftime("%d/%m/%Y"))
        except ValueError:
            parts.append(d)
    more = len(set(dates)) - len(unique)
    text = ", ".join(parts)
    if more > 0:
        text += f" (+{more} ngày khác)"
    return text


def _extract_prices(chunk: str, max_len: int = 20000) -> int | None:
    sub = chunk[:max_len]
    nums = [int(x) for x in re.findall(r'\\"salePrice\\":(\d+)', sub)]
    return min(nums) if nums else None


def _extract_destination(chunk: str, max_len: int = 8000) -> str:
    sub = chunk[:max_len]
    m = re.search(r'\\"destination\\":\\"([^\\"]*)\\"', sub)
    if m:
        return _decode_json_str(m.group(1))
    m = re.search(r'\\"listDestination\\":\[(.*?)\]', sub)
    if m:
        items = re.findall(r'\\"([^\\"]+)\\"', m.group(1))
        if items:
            return " - ".join(_decode_json_str(i) for i in items[:4])
    return ""


def scrape_listing_page(url: str) -> list[dict[str, Any]]:
    """Scrape all tour cards from a Vietravel listing page."""
    resp = requests.get(url, headers=HEADERS, timeout=90)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    text = resp.text

    marker = '\\"pageId\\":'
    if marker not in text:
        raise ValueError(f"Không tìm thấy dữ liệu tour trong trang: {url}")

    tours: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for chunk in text.split(marker)[1:]:
        block = chunk[:15000]
        m = _CARD_RE.search(block)
        if not m:
            continue

        link = m.group(4)
        if link in seen_links:
            continue
        seen_links.add(link)

        title = _decode_json_str(m.group(3))
        dep = _field_in_block(block, "departureName")
        duration = _field_in_block(block, "dayStayText") or _field_in_block(block, "dayNight")
        lich_trinh = _extract_destination(block)
        gia = _extract_prices(block)
        lich_kh = _extract_schedule(block)

        tours.append(
            {
                "cong_ty": COMPANY,
                "thi_truong": "",
                "tuyen_tour": "",
                "ten_tour": title,
                "lich_trinh": lich_trinh,
                "diem_kh": dep,
                "thoi_gian": duration,
                "gia": _fmt_price(gia),
                "lich_kh": lich_kh,
                "link_tour": _hyperlink_formula(link),
                "link_url": link,
                "page_id": m.group(1),
                "page_code": m.group(2),
                "nguon": url,
                "cap_nhat": datetime.now().strftime("%d/%m/%Y %H:%M"),
            }
        )

    return tours


def scrape_all_vietravel_tours() -> pd.DataFrame:
    """Scrape domestic + international listings, then classify market & route."""
    all_tours: list[dict[str, Any]] = []
    for url in SOURCES:
        all_tours.extend(scrape_listing_page(url))
    if not all_tours:
        return pd.DataFrame()
    df = pd.DataFrame(all_tours)
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
        row[COL_MA_TOUR] = str(r.get("page_code", ""))
        row[COL_CAP_NHAT] = str(r.get("cap_nhat", ""))
        row[COL_LINK_RAW] = str(r.get("link_url", ""))
        rows.append(row)
    return rows


def _get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    # Streamlit secrets
    try:
        import streamlit as st

        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
    if os.path.isfile(path):
        creds = Credentials.from_service_account_file(path, scopes=scopes)
        return gspread.authorize(creds)

    raise FileNotFoundError(
        "Chưa cấu hình Google Service Account. "
        "Đặt file credentials.json trong thư mục app hoặc thêm "
        "[gcp_service_account] vào .streamlit/secrets.toml"
    )


def write_to_google_sheet(df: pd.DataFrame, gid: int = GID_VIETRAVEL) -> dict[str, Any]:
    """Overwrite Vietravel worksheet with scraped rows."""
    import gspread

    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet_by_id(gid)
    if ws is None:
        raise ValueError(f"Không tìm thấy sheet gid={gid}")

    rows = tours_to_sheet_rows(df)
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")

    return {
        "sheet_title": ws.title,
        "rows_written": len(rows) - 1,
        "gid": gid,
    }


def sync_vietravel_to_sheet() -> dict[str, Any]:
    """Full pipeline: scrape travel.com.vn → write Google Sheet."""
    df = scrape_all_vietravel_tours()
    if df.empty:
        raise RuntimeError("Không quét được tour nào từ travel.com.vn")
    meta = write_to_google_sheet(df)
    meta["tours_scraped"] = len(df)
    meta["markets"] = int(df["thi_truong"].nunique())
    meta["routes"] = int(df["tuyen_tour"].nunique())
    return meta
