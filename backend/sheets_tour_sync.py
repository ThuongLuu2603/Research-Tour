"""Đồng bộ tour Research Grid ↔ Google Sheet."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from config import settings
from models import Tour

logger = logging.getLogger(__name__)

SHEET_ID = settings.sheet_id
NGUON_GID: dict[str, str] = {
    "Vietravel": settings.gid_vietravel,
    "FindTourGo": settings.gid_findtourgo,
    "Main": settings.gid_main,
}

COL_THI_TRUONG = 2
COL_TUYEN_TOUR = 3
COL_TEN_TOUR = 4
COL_MA_TOUR = 13
COL_LINK_RAW = 26


def _client():
    from google_auth import get_gspread_client
    return get_gspread_client()


def _worksheet(nguon: str):
    gid = NGUON_GID.get(nguon)
    if not gid:
        raise ValueError(f"Không có sheet cho nguồn {nguon}")
    return _client().open_by_key(SHEET_ID).get_worksheet_by_id(int(gid))


def _extract_url(cell: str) -> str:
    if not cell:
        return ""
    m = re.search(r'HYPERLINK\("([^"]+)"', cell, re.I)
    if m:
        return m.group(1)
    if cell.startswith("http"):
        return cell.strip()
    return cell.strip()


def _find_row_index(ws, tour: Tour) -> int | None:
    ma = (tour.ma_tour or "").strip()
    link = (tour.link_url or "").strip()

    if ma:
        try:
            cell = ws.find(ma, in_column=COL_MA_TOUR)
            if cell:
                return cell.row
        except Exception:
            pass

    if link:
        for needle in (link, link.split("?")[0]):
            if not needle:
                continue
            try:
                cell = ws.find(needle, in_column=COL_LINK_RAW)
                if cell:
                    return cell.row
            except Exception:
                pass

    ten = (tour.ten_tour or "").strip()[:80]
    if ten:
        try:
            cell = ws.find(ten, in_column=COL_TEN_TOUR)
            if cell:
                return cell.row
        except Exception:
            pass
    return None


def push_tour_to_sheet(tour: Tour) -> dict:
    if tour.nguon not in NGUON_GID:
        return {"ok": False, "message": f"Nguồn {tour.nguon} không có sheet tương ứng"}

    try:
        ws = _worksheet(tour.nguon)
        row_idx = _find_row_index(ws, tour)
        if not row_idx:
            return {"ok": False, "message": "Không tìm thấy dòng trên Sheet (mã tour/link)"}

        ws.update(
            f"A{row_idx}:C{row_idx}",
            [[tour.cong_ty or "", tour.thi_truong or "", tour.tuyen_tour or ""]],
            value_input_option="USER_ENTERED",
        )
        return {"ok": True, "message": f"Đã cập nhật Sheet dòng {row_idx}", "row": row_idx}
    except Exception as e:
        logger.warning("push_tour_to_sheet failed: %s", e)
        return {"ok": False, "message": str(e)}


def _parse_price(v: str) -> float | None:
    if not v or str(v).strip() in ("", "nan"):
        return None
    cleaned = re.sub(r"[^\d]", "", str(v))
    if not cleaned:
        return None
    val = float(cleaned)
    return val if val > 0 else None


def _row_to_fields(row: list[str]) -> dict | None:
    if len(row) < 4:
        return None
    ten = (row[3] if len(row) > 3 else "").strip()
    if not ten or ten.lower() in ("tên tour", "nan"):
        return None
    gia_raw = row[7] if len(row) > 7 else ""
    link = ""
    if len(row) > COL_LINK_RAW - 1:
        link = _extract_url(row[COL_LINK_RAW - 1])
    if not link and len(row) > 9:
        link = _extract_url(row[9])
    return {
        "cong_ty": (row[0] if len(row) > 0 else "").strip(),
        "thi_truong": (row[1] if len(row) > 1 else "").strip(),
        "tuyen_tour": (row[2] if len(row) > 2 else "").strip(),
        "ten_tour": ten,
        "lich_trinh": (row[4] if len(row) > 4 else "").strip(),
        "diem_kh": (row[5] if len(row) > 5 else "").strip(),
        "thoi_gian": (row[6] if len(row) > 6 else "").strip(),
        "gia_raw": str(gia_raw).strip(),
        "gia": _parse_price(gia_raw),
        "lich_kh": (row[8] if len(row) > 8 else "").strip(),
        "link_url": link,
        "ma_tour": (row[12] if len(row) > 12 else "").strip(),
        "khach_san": (row[10] if len(row) > 10 else "").strip(),
        "hang_khong": (row[11] if len(row) > 11 else "").strip(),
    }


def _find_db_tour(db, nguon: str, fields: dict) -> Tour | None:
    ma = fields.get("ma_tour") or ""
    link = fields.get("link_url") or ""
    if ma:
        t = db.query(Tour).filter(Tour.nguon == nguon, Tour.ma_tour == ma).first()
        if t:
            return t
    if link:
        t = db.query(Tour).filter(Tour.nguon == nguon, Tour.link_url == link).first()
        if t:
            return t
    ten = fields.get("ten_tour") or ""
    if ten:
        return db.query(Tour).filter(Tour.nguon == nguon, Tour.ten_tour == ten).first()
    return None


def merge_sheet_source_to_db(db, nguon: str) -> dict:
    from classification import resolve_company_name, resolve_departure_point
    from seed import parse_ngay, price_segment

    ws = _worksheet(nguon)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {"nguon": nguon, "updated": 0, "skipped": 0}

    updated = skipped = 0
    now = datetime.utcnow()
    for row in rows[1:]:
        fields = _row_to_fields(row)
        if not fields:
            skipped += 1
            continue
        tour = _find_db_tour(db, nguon, fields)
        if not tour:
            skipped += 1
            continue

        tour.cong_ty = resolve_company_name(fields["cong_ty"])[:256]
        tour.thi_truong = fields["thi_truong"][:128]
        tour.tuyen_tour = fields["tuyen_tour"][:256]
        tour.ten_tour = fields["ten_tour"][:512]
        tour.lich_trinh = fields["lich_trinh"]
        tour.diem_kh = resolve_departure_point(fields["diem_kh"])[:256]
        tour.thoi_gian = fields["thoi_gian"][:64]
        tour.gia_raw = fields["gia_raw"][:64]
        tour.gia = fields["gia"]
        tour.lich_kh = fields["lich_kh"]
        if fields["link_url"]:
            tour.link_url = fields["link_url"]
        if fields["ma_tour"]:
            tour.ma_tour = fields["ma_tour"][:64]
        tour.khach_san = fields["khach_san"][:256]
        tour.hang_khong = fields["hang_khong"][:256]
        tour.so_ngay = parse_ngay(fields["thoi_gian"])
        tour.phan_khuc = price_segment(fields["gia"])
        tour.updated_at = now
        updated += 1

    db.commit()
    return {"nguon": nguon, "updated": updated, "skipped": skipped}


def merge_all_sheets_to_db(db) -> dict:
    results = []
    for nguon in NGUON_GID:
        try:
            results.append(merge_sheet_source_to_db(db, nguon))
        except Exception as e:
            results.append({"nguon": nguon, "error": str(e)})
    return {"sources": results, "total_updated": sum(r.get("updated", 0) for r in results)}
