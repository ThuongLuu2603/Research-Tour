"""
Scrape tour listings from travel.com.vn (Vietravel) and sync to Google Sheets.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import requests

from time_vn import fmt_vn

logger = logging.getLogger(__name__)

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
COL_DONG_TOUR = 14  # O — Dòng tour (Tiết kiệm/Tiêu chuẩn/Giá Tốt/ESG&LEI/Cao cấp)
COL_LINK_RAW = 25   # Z

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://travel.com.vn/",
    "Upgrade-Insecure-Requests": "1",
}

# travel.com.vn (Next.js) nhúng dữ liệu tour dạng JSON escaped trong HTML. Mỗi card bắt đầu
# bằng \"pageId\":. Thứ tự field thay đổi theo thời gian (pageTitle/linkShare nằm SAU mảng
# lịch khởi hành), nên trích TỪNG field độc lập thay vì 1 regex theo vị trí (bản cũ vỡ khi
# site đổi cấu trúc → "không quét được tour"). Card hợp lệ = có linkShare.
_PAGEID_RE = re.compile(r"^(\d+)")
_PAGECODE_RE = re.compile(r'\\"pageCode\\":\\"([^\\"]+)\\"')
_PAGETITLE_RE = re.compile(r'\\"pageTitle\\":\\"([^\\"]*)\\"')
_LINKSHARE_RE = re.compile(r'\\"linkShare\\":\\"(https://travel\.com\.vn/chuong-trinh/[^\\"]+)\\"')

# Dòng tour (phân khúc marketing của VTR). tourLineName cho 4 nhóm; nhóm ESG & LEI để tên rỗng
# nên fallback theo tourLineId.
_TOURLINE_NAME_RE = re.compile(r'\\"tourLineName\\":\\"([^\\"]*)\\"')
_TOURLINE_ID_RE = re.compile(r'\\"tourLineId\\":(\d+)')
_TOURLINE_BY_ID = {1: "Tour ESG & LEI", 2: "Tiêu chuẩn", 3: "Tiết kiệm", 4: "Giá Tốt", 6: "Cao cấp"}


def _extract_dong_tour(chunk: str) -> str:
    m = _TOURLINE_NAME_RE.search(chunk)
    name = _decode_json_str(m.group(1)).strip() if m else ""
    if name:
        return name
    mid = _TOURLINE_ID_RE.search(chunk)
    if mid:
        return _TOURLINE_BY_ID.get(int(mid.group(1)), "")
    return ""

_FIELD_RE = {
    "departureName": re.compile(r'\\"departureName\\":\\"([^\\"]*)\\"'),
    "dayStayText": re.compile(r'\\"dayStayText\\":\\"([^\\"]*)\\"'),
    "dayNight": re.compile(r'\\"dayNight\\":\\"([^\\"]*)\\"'),
}

# VTR (Next.js) đặt departureName="$undefined" trong listDepartureDate nhưng
# vẫn lưu departureId ở cấp card. Mapping ID → tên thành phố lấy từ live page
# (cross-check 5 city codes & counts khớp nhau, ngày 2026-06-07).
_DEPARTURE_NAME_RE = re.compile(r'\\"departureName\\":\\"([^\\"]*)\\"')
_DEPARTURE_ID_RE = re.compile(r'\\"departureId\\":(\d+)')
_DEPARTURE_ID_TO_NAME = {
    1: "TP. Hồ Chí Minh",
    3: "Hà Nội",
    4: "Đà Nẵng",
    5: "Cần Thơ",
    8: "Nha Trang",
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


def enrich_market_and_route(
    df: pd.DataFrame,
    progress: Callable[[int, str], None] | None = None,
) -> pd.DataFrame:
    """Phân loại thị trường + tuyến từ quy tắc DB (cùng Main/Vietravel); không khớp → để trống."""
    from classification import _load_route_rules
    from route_rule_matcher import RouteRuleMatcher

    matcher = RouteRuleMatcher(_load_route_rules())
    out = df.copy()
    mk_list: list[str] = []
    rt_list: list[str] = []
    n = len(out)
    for i, (_, row) in enumerate(out.iterrows()):
        ten = str(row.get("ten_tour") or "")
        lich = str(row.get("lich_trinh") or "")
        mk, rt, matched, _rid = matcher.resolve(ten, lich)
        mk_list.append(mk if matched else "")
        rt_list.append(rt if matched else "")
        if progress and n and (i % 50 == 0 or i + 1 == n):
            pct = 70 + int(8 * (i + 1) / n)
            progress(pct, f"Phân loại thị trường/tuyến {i + 1}/{n}…")
    out["thi_truong"] = mk_list
    out["tuyen_tour"] = rt_list
    return out


def _fmt_price(v: int | None) -> str:
    if v is None:
        return ""
    return f"{v:,}".replace(",", ".")


_DEPARTURE_END_RE = (
    re.compile(r'\\"departureDate\\":\\"(\d{4}-\d{2}-\d{2}T[^\\"]+)\\"'),
    re.compile(r'\\"endDate\\":\\"(\d{4}-\d{2}-\d{2}T[^\\"]+)\\"'),
)
_DURATION_LABEL_RE = re.compile(r"(\d+)\s*n\s*(\d+)\s*[dđ]", re.I)
_SAME_DAY_LABELS = frozenset({"trong ngày", "trong ngay", "1 ngày"})


def _duration_from_departure_end(chunk: str) -> tuple[int, int] | None:
    """Suy số ngày/đêm từ departureDate & endDate (VTR hay ghi sai dayStayText)."""
    deps = _DEPARTURE_END_RE[0].findall(chunk)
    ends = _DEPARTURE_END_RE[1].findall(chunk)
    if not deps or not ends:
        return None
    from collections import Counter

    counts: Counter[tuple[int, int]] = Counter()
    for dep_s, end_s in zip(deps, ends):
        try:
            dep = datetime.fromisoformat(dep_s)
            end = datetime.fromisoformat(end_s)
            days = (end.date() - dep.date()).days + 1
            if 1 <= days <= 45:
                counts[(days, max(days - 1, 0))] += 1
        except ValueError:
            continue
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _format_duration_label(days: int, nights: int) -> str:
    if days <= 1:
        return "Trong ngày"
    return f"{days}N{nights}Đ"


def _extract_duration(block: str, chunk: str) -> str:
    """Thời gian tour — ưu tiên suy từ ngày KH/kết thúc khi dayStayText sai."""
    day_stay = (_field_in_block(block, "dayStayText") or _field_in_block(block, "dayNight")).strip()
    computed = _duration_from_departure_end(chunk)

    if computed:
        days, nights = computed
        label = _format_duration_label(days, nights)
        low = day_stay.lower()
        if not day_stay or low in _SAME_DAY_LABELS:
            return label
        if _DURATION_LABEL_RE.search(day_stay):
            return day_stay
        if days >= 2:
            return label

    return day_stay


def _extract_schedule(chunk: str) -> str:
    """Trích toàn bộ ngày KH từ JSON nhúng trong trang (không cắt 12 ngày)."""
    dates = re.findall(r'\\"date\\":\\"(\d{4}-\d{2}-\d{2})', chunk)
    if not dates:
        return ""
    unique = sorted(set(dates))
    parts = []
    for d in unique:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            parts.append(dt.strftime("%d/%m/%Y"))
        except ValueError:
            parts.append(d)
    return ", ".join(parts)


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


def _extract_departure(block: str) -> str:
    """Điểm khởi hành — VTR đặt departureName='$undefined' trong listDepartureDate
    (re.search() match nhầm cái này → trả rỗng cho ~100% card). Fix 2 lớp:
      1) findall + filter $undefined → lấy giá trị valid đầu tiên (thường là card-level)
      2) Fallback: departureId → city map (verify bằng tmp_vtr_verify.py 2026-06-07,
         79/80 card hồi phục được điểm KH trên cả 2 trang)."""
    candidates = [
        _decode_json_str(v) for v in _DEPARTURE_NAME_RE.findall(block)
        if v and v.lower() != "$undefined"
    ]
    if candidates:
        return candidates[0].strip()
    m = _DEPARTURE_ID_RE.search(block)
    if m:
        return _DEPARTURE_ID_TO_NAME.get(int(m.group(1)), "")
    return ""


def scrape_listing_page(url: str) -> list[dict[str, Any]]:
    """Scrape all tour cards from a Vietravel listing page."""
    resp = requests.get(url, headers=HEADERS, timeout=90)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    text = resp.text

    marker = '\\"pageId\\":'
    if marker not in text:
        logger.warning(
            "VTR scrape: không thấy marker pageId tại %s (status=%s, len=%s) — site có thể chặn bot/đổi cấu trúc",
            url, resp.status_code, len(text),
        )
        raise ValueError(f"Không tìm thấy dữ liệu tour trong trang: {url}")

    tours: list[dict[str, Any]] = []
    seen_links: set[str] = set()

    for chunk in text.split(marker)[1:]:
        # Card hợp lệ phải có linkShare (pageTitle/linkShare nằm sau mảng lịch KH → tìm cả chunk).
        link_m = _LINKSHARE_RE.search(chunk)
        if not link_m:
            continue
        link = link_m.group(1)
        if link in seen_links:
            continue
        seen_links.add(link)

        block = chunk[:40000]
        title_m = _PAGETITLE_RE.search(chunk)
        code_m = _PAGECODE_RE.search(chunk)
        pid_m = _PAGEID_RE.match(chunk)

        tours.append(
            {
                "cong_ty": COMPANY,
                "thi_truong": "",
                "tuyen_tour": "",
                "ten_tour": _decode_json_str(title_m.group(1)) if title_m else "",
                "lich_trinh": _extract_destination(block),
                "diem_kh": _extract_departure(block),
                "dong_tour": _extract_dong_tour(chunk),
                "thoi_gian": _extract_duration(block, chunk),
                "gia": _fmt_price(_extract_prices(block)),
                "lich_kh": _extract_schedule(chunk),
                "link_tour": _hyperlink_formula(link),
                "link_url": link,
                "page_id": pid_m.group(1) if pid_m else "",
                "page_code": code_m.group(1) if code_m else "",
                "nguon": url,
                "cap_nhat": fmt_vn(),  # giờ VN (GMT+7), không phải UTC của Render
            }
        )

    if not tours:
        logger.warning(
            "VTR scrape: có marker pageId nhưng 0 card khớp tại %s — JSON có thể đã đổi tên field",
            url,
        )

    return tours


def _fetch_dong_tour_detail(url: str) -> str:
    """Tour KHÔNG có tier ở trang listing (vài tour cuối trang) → lấy tourLineId từ trang chi tiết.

    Trang chi tiết chỉ có ĐÚNG 1 `tourLineId` = tier của chính tour đó (menu chỉ dùng tên/slug),
    nên dùng tourLineId là chắc chắn (không lấy nhầm menu như tourLineName)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        m = _TOURLINE_ID_RE.search(resp.text)
        if m:
            return _TOURLINE_BY_ID.get(int(m.group(1)), "")
    except Exception as e:  # noqa: BLE001
        logger.warning("VTR lấy Dòng tour từ trang chi tiết lỗi (%s): %s", url, e)
    return ""


def scrape_all_vietravel_tours(
    progress: Callable[[int, str], None] | None = None,
    *,
    classify: bool = False,
) -> pd.DataFrame:
    """Scrape domestic + international listings. Phân loại TT/tuyến khi lưu DB (nhanh hơn)."""
    all_tours: list[dict[str, Any]] = []
    n_src = len(SOURCES)
    for i, url in enumerate(SOURCES):
        if progress:
            progress(12 + int(30 * i / max(n_src, 1)), f"Đang tải {url}…")
        all_tours.extend(scrape_listing_page(url))
        if progress:
            progress(28 + int(30 * (i + 1) / max(n_src, 1)), f"Đã quét {len(all_tours)} tour")
    if not all_tours:
        return pd.DataFrame()

    # Bổ sung Dòng tour cho số ít tour mà trang listing thiếu tier (lấy từ trang chi tiết).
    missing = [t for t in all_tours if not (t.get("dong_tour") or "").strip() and t.get("link_url")]
    if missing:
        if progress:
            progress(46, f"Bổ sung Dòng tour cho {len(missing)} tour (trang chi tiết)…")
        for t in missing[:60]:  # giới hạn an toàn — bình thường chỉ 1–3 tour
            dt = _fetch_dong_tour_detail(t["link_url"])
            if dt:
                t["dong_tour"] = dt

    df = pd.DataFrame(all_tours)
    if classify:
        if progress:
            progress(48, f"Phân loại {len(df)} tour…")
        return enrich_market_and_route(df)
    return df


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
    headers[COL_DONG_TOUR] = "Dòng tour"
    headers[COL_LINK_RAW] = "Link"
    return headers


def db_tours_to_dataframe(tours: list) -> pd.DataFrame:
    """Chuyển tour DB (nguon=Vietravel) sang DataFrame để ghi Sheet."""
    records: list[dict[str, Any]] = []
    for t in tours:
        link = str(getattr(t, "link_url", "") or "")
        cap = ""
        if getattr(t, "updated_at", None):
            cap = fmt_vn(t.updated_at)  # updated_at lưu UTC → đổi sang giờ VN khi ghi Sheet
        gia_disp = ""
        if getattr(t, "gia_raw", None):
            gia_disp = str(t.gia_raw)
        elif getattr(t, "gia", None):
            gia_disp = _fmt_price(int(t.gia))
        records.append(
            {
                "cong_ty": getattr(t, "cong_ty", "") or COMPANY,
                "thi_truong": getattr(t, "thi_truong", "") or "",
                "tuyen_tour": getattr(t, "tuyen_tour", "") or "",
                "ten_tour": getattr(t, "ten_tour", "") or "",
                "lich_trinh": getattr(t, "lich_trinh", "") or "",
                "diem_kh": getattr(t, "diem_kh", "") or "",
                "thoi_gian": getattr(t, "thoi_gian", "") or "",
                "gia": gia_disp,
                "lich_kh": getattr(t, "lich_kh", "") or "",
                "link_tour": _hyperlink_formula(link) if link else "",
                "link_url": link,
                "page_code": getattr(t, "ma_tour", "") or "",
                "cap_nhat": cap,
                "dong_tour": getattr(t, "dong_tour", "") or "",
            }
        )
    return pd.DataFrame(records)


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
        row[COL_DONG_TOUR] = str(r.get("dong_tour", ""))
        row[COL_LINK_RAW] = str(r.get("link_url", ""))
        rows.append(row)
    return rows


def _get_gspread_client():
    from google_auth import get_gspread_client
    return get_gspread_client()


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
