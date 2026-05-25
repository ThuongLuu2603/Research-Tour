#!/usr/bin/env python3
"""
Seed initial data:
  1. Create default admin users
  2. Import tour data from bundled CSV snapshots (or Google Sheets fallback)
"""
from __future__ import annotations

import csv
import gc
import gzip
import io
import logging
import re
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

from database import SessionLocal, init_db
from models import Tour, User
from api.auth import hash_password
from config import settings

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
INSERT_BATCH = 50

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
]

MAIN_CHUNK_FILES = sorted(DATA_DIR.glob("main_*.csv.gz"))

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


def bundled_files_info() -> list[dict]:
    files = []
    for p in sorted(DATA_DIR.glob("*.csv.gz")):
        files.append({"name": p.name, "size_kb": p.stat().st_size // 1024})
    return files


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
            {"username": "admin", "password": "admin123", "display_name": "Admin", "role": "admin"},
            {"username": "analyst", "password": "analyst123", "display_name": "Analyst", "role": "analyst"},
        ]
        for u in users:
            existing = db.query(User).filter(User.username == u["username"]).first()
            if not existing:
                db.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    display_name=u["display_name"],
                    role=u.get("role", "analyst"),
                ))
                logger.info("Created user: %s", u["username"])
            else:
                if u["username"] == "admin":
                    existing.role = "admin"
                logger.info("User already exists: %s", u["username"])
        db.commit()
    finally:
        db.close()


def _map_row(raw: dict[str, str]) -> dict[str, str]:
    return {HEADER_MAP[k]: (v or "") for k, v in raw.items() if k in HEADER_MAP}


def _row_to_mapping(row: dict[str, str], nguon: str) -> dict | None:
    from classification import resolve_company_name, resolve_departure_point

    ten_tour = str(row.get("ten_tour") or "").strip()
    if not ten_tour or ten_tour.lower() in ("nan", "tên tour"):
        return None

    gia_raw = str(row.get("gia_raw") or "").strip()
    gia = parse_price(gia_raw)
    thoi_gian = str(row.get("thoi_gian") or "").strip()
    from link_utils import normalize_tour_link
    link_url = normalize_tour_link(str(row.get("link_url") or "").strip()) or normalize_tour_link(str(row.get("link_raw") or "").strip())
    now = datetime.utcnow()

    return {
        "cong_ty": resolve_company_name(str(row.get("cong_ty") or "").strip())[:256],
        "thi_truong": str(row.get("thi_truong") or "").strip()[:128],
        "tuyen_tour": str(row.get("tuyen_tour") or "").strip()[:256],
        "ten_tour": ten_tour[:512],
        "lich_trinh": str(row.get("lich_trinh") or "").strip(),
        "diem_kh": resolve_departure_point(str(row.get("diem_kh") or "").strip())[:256],
        "thoi_gian": thoi_gian[:64],
        "gia_raw": gia_raw[:64],
        "gia": gia,
        "lich_kh": str(row.get("lich_kh") or "").strip(),
        "link_url": link_url,
        "ma_tour": str(row.get("ma_tour") or "").strip()[:64],
        "khach_san": str(row.get("khach_san") or "").strip()[:256],
        "hang_khong": str(row.get("hang_khong") or "").strip()[:256],
        "so_ngay": parse_ngay(thoi_gian),
        "phan_khuc": price_segment(gia),
        "nguon": nguon,
        "analyst_note": "",
        "flagged": False,
        "created_at": now,
        "updated_at": now,
    }


def _iter_local_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            yield _map_row(raw)


def _iter_sheet_rows(nguon: str, gid: str, snapshot: str):
    local = DATA_DIR / snapshot
    if local.exists():
        logger.info("Reading %s from %s", nguon, local.name)
        yield from _iter_local_gz(local)
        return

    url = (
        f"https://docs.google.com/spreadsheets/d/{settings.sheet_id}"
        f"/export?format=csv&gid={gid}"
    )
    logger.info("Reading %s from Google URL", nguon)
    with urllib.request.urlopen(url, timeout=180) as resp:
        text = resp.read().decode("utf-8")
    for raw in csv.DictReader(io.StringIO(text)):
        yield _map_row(raw)


def _bulk_insert_rows(db, nguon: str, rows_iter) -> int:
    count = 0
    batch: list[dict] = []
    for row in rows_iter:
        mapping = _row_to_mapping(row, nguon)
        if not mapping:
            continue
        batch.append(mapping)
        if len(batch) >= INSERT_BATCH:
            db.bulk_insert_mappings(Tour, batch)
            db.commit()
            count += len(batch)
            batch.clear()
            db.expunge_all()
    if batch:
        db.bulk_insert_mappings(Tour, batch)
        db.commit()
        count += len(batch)
        batch.clear()
        db.expunge_all()
    return count


def _set_progress(nguon: str, count: int, msg: str = "") -> None:
    with _import_lock:
        _import_status["current_source"] = nguon
        _import_status["rows_done"] = count
        _import_status["message"] = msg or f"Đang import {nguon}: {count:,} dòng..."


def import_sheet_tab(nguon: str, gid: str, snapshot: str, replace: bool = False) -> int:
    db = SessionLocal()
    try:
        if replace:
            deleted = db.query(Tour).filter(Tour.nguon == nguon).delete()
            db.commit()
            logger.info("Removed %s %s tours", deleted, nguon)
        count = _bulk_insert_rows(db, nguon, _iter_sheet_rows(nguon, gid, snapshot))
        logger.info("Finished %s: %s tours", nguon, count)
        _set_progress(nguon, count, f"Xong {nguon}: {count:,} tour")
        return count
    except Exception:
        db.rollback()
        logger.exception("Import failed for %s", nguon)
        raise
    finally:
        db.close()
        gc.collect()


def import_main_chunks() -> int:
    """Import Main tab from small chunk files (memory-safe on Render free tier)."""
    chunks = MAIN_CHUNK_FILES or [DATA_DIR / "main.csv.gz"]
    if not any(p.exists() for p in chunks):
        logger.warning("No Main chunk files found, falling back to single file / URL")
        return import_sheet_tab("Main", settings.gid_main, "main.csv.gz", replace=True)

    db = SessionLocal()
    total = 0
    try:
        deleted = db.query(Tour).filter(Tour.nguon == "Main").delete()
        db.commit()
        logger.info("Removed %s Main tours, importing %s chunks", deleted, len(chunks))

        for idx, chunk_path in enumerate(chunks, 1):
            if not chunk_path.exists():
                continue
            _set_progress("Main", total, f"Main chunk {idx}/{len(chunks)}...")
            added = _bulk_insert_rows(db, "Main", _iter_local_gz(chunk_path))
            total += added
            db.expunge_all()
            gc.collect()
            logger.info("Main chunk %s/%s: +%s (total %s)", idx, len(chunks), added, total)
            _set_progress("Main", total)

        logger.info("Finished Main: %s tours from %s chunks", total, len(chunks))
        return total
    except Exception:
        db.rollback()
        logger.exception("Main chunk import failed at %s tours", total)
        raise
    finally:
        db.close()
        gc.collect()


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
            results[nguon] = count
            continue
        logger.info("%s incomplete (%s) — importing", nguon, count)
        try:
            results[nguon] = import_sheet_tab(nguon, gid, snapshot, replace=count > 0)
        except Exception as e:
            logger.error("%s failed: %s", nguon, e)
            results[nguon] = source_count(nguon)

    main_count = source_count("Main")
    if main_count < EXPECTED_MIN["Main"]:
        logger.info("Main incomplete (%s) — importing chunks", main_count)
        try:
            results["Main"] = import_main_chunks()
        except Exception as e:
            logger.error("Main failed: %s", e)
            results["Main"] = source_count("Main")
    else:
        results["Main"] = main_count

    logger.info("Sync done — total %s — %s", tour_count(), results)
    return results


def start_import_background() -> bool:
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
                _import_status["message"] = f"Import xong — đang đồng bộ Sheet live…"
            try:
                from sheets_tour_sync import merge_all_sheets_to_db
                db = SessionLocal()
                try:
                    sync_result = merge_all_sheets_to_db(db)
                    logger.info("Sheet live sync: %s", sync_result)
                finally:
                    db.close()
            except Exception as sync_err:
                logger.warning("Sheet live sync skipped: %s", sync_err)
            with _import_lock:
                _import_status["message"] = f"Import hoàn tất — {tour_count():,} tour"
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
    if "--sync" in sys.argv or len(sys.argv) == 1:
        import_missing_sheets()
    print(f"Total: {tour_count()}")
    for nguon, _, _ in SHEET_SOURCES:
        print(f"  {nguon}: {source_count(nguon)}")
    print(f"  Main: {source_count('Main')}")
