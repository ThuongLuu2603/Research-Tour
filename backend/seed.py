#!/usr/bin/env python3
"""
Seed initial data:
  1. Create default admin users
  2. Import tour data from bundled CSV snapshots (or Google Sheets fallback)
"""
from __future__ import annotations

import csv
import gzip
import io
import logging
import re
import sys
import threading
import urllib.request
from pathlib import Path

from database import SessionLocal, init_db
from models import Tour, User
from api.auth import hash_password
from config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
BULK_SIZE = 500

HEADER_MAP = {
    "Tên Công Ty": "cong_ty",
    "Thị trường": "thi_truong",
    "Tuyến tour": "tuyen_tour",
    " Tuyến tour": "tuyen_tour",
    "Tên Tour": "ten_tour",
    "Lịch trình": "lich_trinh",
    "Điểm khởi hành": "diem_kh",
    "Thời gian": "thoi_gian",
    "Giá": "gia_raw",
    "Lịch khởi hành": "lich_kh",
    "Link tour": "link_url",
    "Khách sạn": "khach_san",
    "Hàng không": "hang_khong",
    "Mã tour": "ma_tour",
    "Link": "link_raw",
}

SHEET_SOURCES: list[tuple[str, str, str]] = [
    ("Vietravel", settings.gid_vietravel, "vietravel.csv.gz"),
    ("FindTourGo", settings.gid_findtourgo, "findtourgo.csv.gz"),
    ("Main", settings.gid_main, "main.csv.gz"),
]

EXPECTED_MIN: dict[str, int] = {
    "Vietravel": 100,
    "FindTourGo": 500,
    "Main": 7500,
}

_import_lock = threading.Lock()
_import_status: dict = {
    "running": False,
    "message": "",
    "current_source": "",
    "rows_done": 0,
    "error": None,
}


def get_import_status() -> dict:
    with _import_lock:
        return dict(_import_status)


def parse_price(v) -> float | None:
    if not v or str(v).strip() in ("", "nan"):
        return None
    cleaned = re.sub(r"[^\d]", "", str(v))
    if not cleaned:
        return None
    val = float(cleaned)
    return val if val > 0 else None


def parse_ngay(thoi_gian: str) -> float | None:
    if not thoi_gian:
        return None
    s = str(thoi_gian).strip().lower()
    m = re.search(r"(?<!\d)(\d{1,2})\s*n", s)
    if m:
        d = float(m.group(1))
        return d if 0 < d <= 45 else None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*ng", s)
    if m:
        d = float(m.group(1).replace(",", "."))
        return d if 0 < d <= 45 else None
    return None


def price_segment(gia: float | None) -> str:
    if not gia:
        return "Chưa có giá"
    if gia < 2e6:
        return "Budget (< 2tr)"
    if gia < 5e6:
        return "Mid (2–5tr)"
    if gia < 15e6:
        return "Premium (5–15tr)"
    return "Luxury (> 15tr)"


def create_default_users() -> None:
    db = SessionLocal()
    try:
        users = [
            {"username": "admin", "password": "admin123", "display_name": "Admin"},
            {"username": "analyst", "password": "analyst123", "display_name": "Analyst"},
        ]
        for u in users:
            if not db.query(User).filter(User.username == u["username"]).first():
                db.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    display_name=u["display_name"],
                ))
                logger.info("Created user: %s", u["username"])
        db.commit()
    finally:
        db.close()


def _map_row(raw: dict[str, str]) -> dict[str, str]:
    return {HEADER_MAP[k]: (v or "") for k, v in raw.items() if k in HEADER_MAP}


def _row_to_tour(row: dict[str, str], nguon: str) -> Tour | None:
    ten_tour = str(row.get("ten_tour") or "").strip()
    if not ten_tour or ten_tour.lower() in ("nan", "tên tour"):
        return None

    gia_raw = str(row.get("gia_raw") or "").strip()
    gia = parse_price(gia_raw)
    thoi_gian = str(row.get("thoi_gian") or "").strip()
    link_url = str(row.get("link_url") or "").strip() or str(row.get("link_raw") or "").strip()

    return Tour(
        cong_ty=str(row.get("cong_ty") or "").strip(),
        thi_truong=str(row.get("thi_truong") or "").strip(),
        tuyen_tour=str(row.get("tuyen_tour") or "").strip(),
        ten_tour=ten_tour,
        lich_trinh=str(row.get("lich_trinh") or "").strip(),
        diem_kh=str(row.get("diem_kh") or "").strip(),
        thoi_gian=thoi_gian,
        gia_raw=gia_raw,
        gia=gia,
        lich_kh=str(row.get("lich_kh") or "").strip(),
        link_url=link_url,
        ma_tour=str(row.get("ma_tour") or "").strip(),
        khach_san=str(row.get("khach_san") or "").strip(),
        hang_khong=str(row.get("hang_khong") or "").strip(),
        so_ngay=parse_ngay(thoi_gian),
        phan_khuc=price_segment(gia),
        nguon=nguon,
    )


def _open_csv_rows(nguon: str, gid: str, snapshot: str):
    local = DATA_DIR / snapshot
    if local.exists():
        logger.info("Reading %s from bundled file %s", nguon, local)
        with gzip.open(local, "rt", encoding="utf-8", newline="") as f:
            for raw in csv.DictReader(f):
                yield _map_row(raw)
        return

    url = (
        f"https://docs.google.com/spreadsheets/d/{settings.sheet_id}"
        f"/export?format=csv&gid={gid}"
    )
    logger.info("Reading %s from URL %s", nguon, url)
    with urllib.request.urlopen(url, timeout=180) as resp:
        text = resp.read().decode("utf-8")
    for raw in csv.DictReader(io.StringIO(text)):
        yield _map_row(raw)


def _set_progress(nguon: str, count: int, msg: str = "") -> None:
    with _import_lock:
        _import_status["current_source"] = nguon
        _import_status["rows_done"] = count
        _import_status["message"] = msg or f"Đang import {nguon}: {count:,} dòng..."


def import_sheet_tab(nguon: str, gid: str, snapshot: str, replace: bool = False) -> int:
    """Bulk-import one tab. Fast replace mode for large Main sheet."""
    db = SessionLocal()
    count = 0
    batch: list[Tour] = []
    try:
        if replace:
            deleted = db.query(Tour).filter(Tour.nguon == nguon).delete()
            db.commit()
            logger.info("Removed %s existing %s tours", deleted, nguon)

        for row in _open_csv_rows(nguon, gid, snapshot):
            tour = _row_to_tour(row, nguon)
            if not tour:
                continue

            if replace:
                batch.append(tour)
                if len(batch) >= BULK_SIZE:
                    db.bulk_save_objects(batch)
                    db.commit()
                    count += len(batch)
                    batch = []
                    _set_progress(nguon, count)
                    if count % 2000 == 0:
                        logger.info("%s: %s rows...", nguon, count)
            else:
                existing = None
                if tour.ma_tour:
                    existing = (
                        db.query(Tour)
                        .filter(Tour.nguon == nguon, Tour.ma_tour == tour.ma_tour)
                        .first()
                    )
                if not existing:
                    existing = (
                        db.query(Tour)
                        .filter(
                            Tour.nguon == nguon,
                            Tour.ten_tour == tour.ten_tour,
                            Tour.cong_ty == tour.cong_ty,
                        )
                        .first()
                    )
                if existing:
                    for field in (
                        "cong_ty", "thi_truong", "tuyen_tour", "ten_tour", "lich_trinh",
                        "diem_kh", "thoi_gian", "gia_raw", "gia", "lich_kh", "link_url",
                        "ma_tour", "khach_san", "hang_khong", "so_ngay", "phan_khuc",
                    ):
                        setattr(existing, field, getattr(tour, field))
                else:
                    db.add(tour)
                count += 1

        if batch:
            db.bulk_save_objects(batch)
            db.commit()
            count += len(batch)

        if not replace:
            db.commit()

        logger.info("Finished %s: %s tours", nguon, count)
        _set_progress(nguon, count, f"Xong {nguon}: {count:,} tour")
    except Exception:
        db.rollback()
        logger.exception("Import failed for %s", nguon)
        raise
    finally:
        db.close()
    return count


def source_count(nguon: str) -> int:
    db = SessionLocal()
    try:
        return db.query(Tour).filter(Tour.nguon == nguon).count()
    finally:
        db.close()


def import_missing_sheets() -> dict[str, int]:
    results: dict[str, int] = {}
    for nguon, gid, snapshot in SHEET_SOURCES:
        count = source_count(nguon)
        expected = EXPECTED_MIN.get(nguon, 1)
        if count >= expected:
            logger.info("%s OK (%s >= %s)", nguon, count, expected)
            results[nguon] = count
            continue
        logger.info("%s incomplete (%s < %s) — importing", nguon, count, expected)
        try:
            results[nguon] = import_sheet_tab(nguon, gid, snapshot, replace=count > 0)
        except Exception as e:
            logger.error("%s import error: %s", nguon, e)
            results[nguon] = source_count(nguon)
    total = tour_count()
    logger.info("Sync complete — total tours: %s — breakdown: %s", total, results)
    return results


def start_import_background() -> bool:
    """Start import in background thread. Returns False if already running."""
    with _import_lock:
        if _import_status["running"]:
            return False
        _import_status.update({
            "running": True,
            "message": "Đang bắt đầu import...",
            "current_source": "",
            "rows_done": 0,
            "error": None,
        })

    def _run():
        try:
            import_missing_sheets()
            with _import_lock:
                _import_status["message"] = "Import hoàn tất"
        except Exception as e:
            logger.exception("Background import failed")
            with _import_lock:
                _import_status["error"] = str(e)
                _import_status["message"] = f"Lỗi: {e}"
        finally:
            with _import_lock:
                _import_status["running"] = False

    threading.Thread(target=_run, daemon=True, name="sheet-import").start()
    return True


def tour_count() -> int:
    db = SessionLocal()
    try:
        return db.query(Tour).count()
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    create_default_users()

    if "--users-only" in sys.argv:
        print("Seed completed (users only).")
    elif "--import-all" in sys.argv:
        for nguon, gid, snap in SHEET_SOURCES:
            import_sheet_tab(nguon, gid, snap, replace="--replace" in sys.argv)
        print("Seed completed.")
    elif "--sync" in sys.argv or len(sys.argv) == 1:
        import_missing_sheets()
        print("Seed completed.")
    else:
        print(f"Total tours: {tour_count()}")
        for nguon, _, _ in SHEET_SOURCES:
            print(f"  {nguon}: {source_count(nguon)}")
