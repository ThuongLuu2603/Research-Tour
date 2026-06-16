"""
Scrape tour listings from travel.com.vn (Vietravel) and sync to Google Sheets.

Vietravel đã đổi web sang SPA (Single Page App) → dữ liệu KHÔNG còn nhúng trong HTML.
Toàn bộ tour lấy qua API JSON `api2.travel.com.vn`. Bản HTML-scrape cũ đã chết.

API:
    POST https://api2.travel.com.vn/core/tour/search-tour-file-filter?page={page}&pageSize=80
    Body: {"fromDate": "<today YYYY-MM-DD>", "keywords": "<viet-nam|nuoc-ngoai>"}
    Auth: Bearer <token JWT tĩnh, public key của web app, exp năm 9999> + clientid.

Response (đã verify 2026-06-10):
    {status:1, code:200, totalRecord, totalPage (theo pageSize), response:{listTour:[...]}}
Mỗi tour: pageTitle / priceFinal / tourLineName / tourLineId / departureName /
          dayStayText / pageCode / linkShare / pageId / listDepartureDate[].date
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

import pandas as pd
import requests

from time_vn import fmt_vn

logger = logging.getLogger(__name__)

COMPANY = "Vietravel"
SHEET_ID = "1sI34D88zsmSrN7Jf9fS3jh4aUvaep-blxnBR1CGq9eM"
GID_VIETRAVEL = 620817544

# ── API JSON (SPA) ──────────────────────────────────────────────────────────
API_URL = "https://api2.travel.com.vn/core/tour/search-tour-file-filter"
# Token JWT tĩnh của web app (exp năm 9999) — public key baked vào site travel.com.vn.
# Cùng giá trị với scripts/debug_vietravel_api.py.
_BEARER = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJuIjoid2ViX3RyYXZlbCIsImMiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGIi"
    "LCJ3IjoiVHJhdmVsLmNvbS52bnxodHRwczovL3RyYXZlbC5jb20udm4iLCJwIjoiVHJhdmVsfFRyYXZlbCIs"
    "InUiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGJ8NDY5NGM2ODItNDZjNy00Y2M2LWEx"
    "OTQtOTY4ZWE5NWU5Y2M5IiwiciI6IkFkbWluIiwiZXhwIjoyNTM0MDIyNzU2MDAsImlzcyI6InRyYXZlbC5j"
    "b20udm4iLCJhdWQiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGIifQ."
    "aX3hZxdsCkV4qr_0l_Z4RsAXfkMY4VBSFIb0VTobVOQ"
)
_CLIENT_ID = "AB7296F2-0489-4B4D-85A2-09006CCB3E0B"

# Header dùng để GỌI API (khác với HEADERS browser cũ — giữ HEADERS riêng cho
# backward-compat với script debug HTML cũ).
API_HEADERS = {
    "accept": "application/json",
    "accept-language": "vi",
    "authorization": f"Bearer {_BEARER}",
    "clientid": _CLIENT_ID,
    "client-url": "https://travel.com.vn/du-lich-viet-nam.aspx",
    "content-type": "application/json",
    "origin": "https://travel.com.vn",
    "referer": "https://travel.com.vn/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}

PAGE_SIZE = 80
_MAX_PAGES = 100  # cap an toàn tránh loop vô hạn nếu totalPage sai
_SLEEP_BETWEEN = 0.4  # giây — API có x-rate-limit, nghỉ nhẹ giữa các request

# Markets → keyword API. SOURCES cũ (du-lich-viet-nam / du-lich-nuoc-ngoai) đổi
# thành keyword "viet-nam" (nội địa) + "nuoc-ngoai" (outbound). Cả 2 đã verify
# trả data (227 + 481 tour ngày 2026-06-10).
MARKETS: list[tuple[str, str]] = [
    ("viet-nam", "Nội địa"),
    ("nuoc-ngoai", "Nước ngoài"),
]

# SOURCES giữ lại cho backward-compat (script debug cũ import). Không còn dùng
# để scrape (HTML đã chết) — chỉ là tham chiếu.
SOURCES = [
    "https://travel.com.vn/du-lich-viet-nam.aspx",
    "https://travel.com.vn/du-lich-nuoc-ngoai.aspx",
]

# Header browser cũ — giữ cho backward-compat (script debug HTML import HEADERS).
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

# Cột A–Z (26 cột); Z = link thô cho UI
SHEET_NUM_COLS = 26
COL_LINK_TOUR = 9   # J
COL_MA_TOUR = 12    # M
COL_CAP_NHAT = 13   # N
COL_DONG_TOUR = 14  # O — Dòng tour (Tiết kiệm/Tiêu chuẩn/Giá Tốt/ESG&LEI/Cao cấp)
COL_LINK_RAW = 25   # Z

# Dòng tour (phân khúc marketing của VTR). tourLineName cho 4 nhóm; nhóm ESG & LEI
# để tên rỗng nên fallback theo tourLineId.
_TOURLINE_BY_ID = {1: "Tour ESG & LEI", 2: "Tiêu chuẩn", 3: "Tiết kiệm", 4: "Giá Tốt", 6: "Cao cấp"}


def _hyperlink_formula(url: str) -> str:
    """Google Sheets VN dùng dấu ; trong công thức."""
    safe = (url or "").replace('"', '""')
    return f'=HYPERLINK("{safe}";"Xem chi tiết")'


def _fmt_price(v: int | float | None) -> str:
    if v is None:
        return ""
    return f"{int(v):,}".replace(",", ".")


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


# ── Mapping 1 tour JSON → dict (giữ ĐÚNG keys như bản cũ) ────────────────────

def _dong_tour(tour: dict[str, Any]) -> str:
    """tourLineName; nếu rỗng → fallback theo tourLineId."""
    name = str(tour.get("tourLineName") or "").strip()
    if name:
        return name
    tid = tour.get("tourLineId")
    if tid is not None:
        try:
            return _TOURLINE_BY_ID.get(int(tid), "")
        except (TypeError, ValueError):
            return ""
    return ""


def _price(tour: dict[str, Any]) -> int | None:
    """gia = priceFinal (API đã sạch, KHÔNG dùng heuristic deposit cũ).
    Nếu priceFinal falsy/0 → lấy min salePrice trong listDepartureDate."""
    pf = tour.get("priceFinal")
    try:
        if pf and float(pf) > 0:
            return int(float(pf))
    except (TypeError, ValueError):
        pass

    prices: list[int] = []
    for dep in tour.get("listDepartureDate") or []:
        sp = (dep or {}).get("salePrice")
        try:
            if sp and float(sp) > 0:
                prices.append(int(float(sp)))
        except (TypeError, ValueError):
            continue
    return min(prices) if prices else None


def _schedule(tour: dict[str, Any]) -> str:
    """lich_kh từ listDepartureDate[].date (ISO) → "DD/MM/YYYY" nối ", ".

    Format DD/MM/YYYY khớp departure_parser.parse_departure_dates (DATE_RE) →
    tính tần suất đoàn KH chính xác (có năm explicit, ưu tiên cao nhất)."""
    dates: list[datetime] = []
    for dep in tour.get("listDepartureDate") or []:
        raw = (dep or {}).get("date")
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        dates.append(dt)
    if not dates:
        return ""
    uniq = sorted({(d.year, d.month, d.day): d for d in dates}.values())
    return ", ".join(d.strftime("%d/%m/%Y") for d in uniq)


def _tour_to_dict(tour: dict[str, Any], keyword: str) -> dict[str, Any]:
    """Map 1 tour JSON → dict output (keys GIỮ NGUYÊN để sheet sync hoạt động)."""
    link = str(tour.get("linkShare") or "").strip()
    hotel = str(tour.get("hotel") or "").strip()
    pid = tour.get("pageId")
    return {
        "cong_ty": COMPANY,
        "thi_truong": "",          # rule classify sau
        "tuyen_tour": "",          # rule classify sau
        "ten_tour": str(tour.get("pageTitle") or "").strip(),
        # lich_trinh: GIỮ TRỐNG (đã fix trước — không bịa từ destination).
        "lich_trinh": "",
        "diem_kh": str(tour.get("departureName") or "").strip(),
        "dong_tour": _dong_tour(tour),
        "thoi_gian": str(tour.get("dayStayText") or "").strip(),
        "gia": _fmt_price(_price(tour)),
        "lich_kh": _schedule(tour),
        "khach_san": hotel,
        "hang_khong": "",          # API không có airline riêng
        "link_tour": _hyperlink_formula(link) if link else "",
        "link_url": link,
        "page_id": str(pid) if pid is not None else "",
        "page_code": str(tour.get("pageCode") or "").strip(),
        "nguon": keyword,
        "cap_nhat": fmt_vn(),  # giờ VN (GMT+7), không phải UTC của Render
    }


def _variant_external_id(page_code: str, link: str, ten: str, price: int | None) -> str:
    """external_id ổn định cho 1 BIẾN THỂ GIÁ của chương trình: base + '#<giá>'.
    Cùng (chương trình, giá) → cùng id qua các lần chạy; khác giá → id khác → tách dòng DB."""
    from tour_identity import compute_external_id

    base = compute_external_id("Vietravel", ma_tour=page_code, link_url=link, ten_tour=ten)
    return f"{base}#{int(price)}" if price else base


def _price_groups_from_departures(tour: dict[str, Any]) -> dict[int, list[datetime]]:
    """Gom listDepartureDate theo salePrice → {giá(int): [ngày]}. Ngày không có giá → bỏ."""
    groups: dict[int, list[datetime]] = defaultdict(list)
    for dep in tour.get("listDepartureDate") or []:
        if not isinstance(dep, dict):
            continue
        sp = dep.get("salePrice")
        raw = dep.get("date")
        try:
            price = int(float(sp)) if sp and float(sp) > 0 else None
        except (TypeError, ValueError):
            price = None
        if price is None or not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        groups[price].append(dt)
    return groups


def _tour_to_rows(tour: dict[str, Any], keyword: str) -> list[dict[str, Any]]:
    """1 chương trình → NHIỀU dòng: ngày CÙNG giá gộp 1 dòng, KHÁC giá tách dòng riêng.

    Mỗi dòng giữ chung mọi field (tên/điểm KH/thời gian/link/mã tour…), chỉ khác `gia`
    + `lich_kh` (các ngày của mức giá đó) + `external_id` (định danh riêng theo giá).
    Không có giá-theo-ngày (listDepartureDate rỗng) → 1 dòng fallback (giá = priceFinal/min)."""
    base = _tour_to_dict(tour, keyword)
    groups = _price_groups_from_departures(tour)
    if not groups:
        base["external_id"] = _variant_external_id(
            base["page_code"], base["link_url"], base["ten_tour"], None
        )
        return [base]

    rows: list[dict[str, Any]] = []
    for price in sorted(groups, key=lambda p: min(groups[p])):  # theo ngày sớm nhất
        dates = sorted({(d.year, d.month, d.day): d for d in groups[price]}.values())
        row = dict(base)
        row["gia"] = _fmt_price(price)
        row["lich_kh"] = ", ".join(d.strftime("%d/%m/%Y") for d in dates)
        row["external_id"] = _variant_external_id(
            base["page_code"], base["link_url"], base["ten_tour"], price
        )
        rows.append(row)
    return rows


def fetch_tours_from_api(keyword: str) -> list[dict[str, Any]]:
    """Gọi API JSON, paginate tất cả trang cho 1 keyword, trả list[dict] tour.

    Flow:
      - POST page=0 → đọc totalPage. Loop page 0..totalPage-1 (cap _MAX_PAGES),
        dừng sớm nếu listTour rỗng (an toàn nếu totalPage sai).
      - Dedup theo pageId (fallback pageCode/linkShare).
      - Sleep nhẹ giữa request tránh rate limit.
      - KHÔNG raise — lỗi → log + trả những gì đã có (hoặc []).
    """
    from datetime import date

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    body = {"fromDate": date.today().isoformat(), "keywords": keyword}
    total_page: int | None = None
    page = 0

    while page < _MAX_PAGES:
        if total_page is not None and page >= total_page:
            break
        try:
            r = requests.post(
                API_URL,
                params={"page": page, "pageSize": PAGE_SIZE},
                json=body,
                headers=API_HEADERS,
                timeout=30,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("VTR API request lỗi (keyword=%s page=%s): %s", keyword, page, e)
            break

        if r.status_code != 200:
            logger.warning(
                "VTR API status=%s (keyword=%s page=%s, len=%s) — token hết hạn / API đổi?",
                r.status_code, keyword, page, len(r.content),
            )
            break

        try:
            data = r.json()
        except ValueError as e:
            logger.warning("VTR API JSON parse lỗi (keyword=%s page=%s): %s", keyword, page, e)
            break

        status = data.get("status")
        resp = data.get("response") or {}
        list_tour = resp.get("listTour") or []

        if total_page is None:
            total_page = data.get("totalPage")
            try:
                total_page = int(total_page) if total_page is not None else None
            except (TypeError, ValueError):
                total_page = None

        if status != 1 or (page == 0 and not list_tour):
            logger.warning(
                "VTR API trả 0 tour cho keyword %r (status=%s, page=%s) — "
                "có thể token hết hạn / API đổi / keyword không nhận.",
                keyword, status, page,
            )
            break

        if not list_tour:
            break  # hết data (totalPage có thể sai)

        for tour in list_tour:
            if not isinstance(tour, dict):
                continue
            key = (
                str(tour.get("pageId"))
                or str(tour.get("pageCode"))
                or str(tour.get("linkShare"))
            )
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.extend(_tour_to_rows(tour, keyword))  # tách dòng theo giá

        page += 1
        if total_page is not None and page >= total_page:
            break

        import time
        time.sleep(_SLEEP_BETWEEN)

    if not out:
        logger.warning("VTR API: 0 tour cho keyword %r — kiểm tra token/keyword/API.", keyword)

    return out


def scrape_all_vietravel_tours(
    progress: Callable[[int, str], None] | None = None,
    *,
    classify: bool = False,
) -> pd.DataFrame:
    """Scrape nội địa + outbound qua API JSON. Phân loại TT/tuyến khi lưu DB."""
    all_tours: list[dict[str, Any]] = []
    n_mk = len(MARKETS)
    for i, (keyword, label) in enumerate(MARKETS):
        if progress:
            progress(12 + int(30 * i / max(n_mk, 1)), f"Đang tải thị trường {label}…")
        tours = fetch_tours_from_api(keyword)
        if not tours:
            logger.warning("VTR: keyword %r (%s) trả 0 tour.", keyword, label)
        all_tours.extend(tours)
        if progress:
            progress(28 + int(30 * (i + 1) / max(n_mk, 1)), f"Đã quét {len(all_tours)} tour")

    if not all_tours:
        return pd.DataFrame()

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
        row[10] = str(r.get("khach_san", ""))
        row[11] = str(r.get("hang_khong", ""))
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
    import gspread  # noqa: F401

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
    """Full pipeline: scrape travel.com.vn API → write Google Sheet."""
    df = scrape_all_vietravel_tours()
    if df.empty:
        raise RuntimeError("Không quét được tour nào từ travel.com.vn")
    meta = write_to_google_sheet(df)
    meta["tours_scraped"] = len(df)
    meta["markets"] = int(df["thi_truong"].nunique())
    meta["routes"] = int(df["tuyen_tour"].nunique())
    return meta
