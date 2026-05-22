#!/usr/bin/env python3
"""
Seed initial data:
  1. Create default admin users
  2. Import tour data from Google Sheets (Main, Vietravel, FindTourGo)
"""
from __future__ import annotations

import logging
import re
import sys

import pandas as pd

from database import SessionLocal, init_db
from models import Tour, User
from api.auth import hash_password
from config import settings

logger = logging.getLogger(__name__)

BATCH_SIZE = 200

# Vietnamese sheet headers → model fields
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

# Smaller tabs first so the UI gets data sooner during background import
SHEET_SOURCES = [
    ("Vietravel", settings.gid_vietravel),
    ("FindTourGo", settings.gid_findtourgo),
    ("Main", settings.gid_main),
]


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
                user = User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    display_name=u["display_name"],
                )
                db.add(user)
                logger.info("Created user: %s", u["username"])
            else:
                logger.info("User already exists: %s", u["username"])
        db.commit()
    finally:
        db.close()


def _load_sheet(gid: str) -> pd.DataFrame | None:
    url = (
        f"https://docs.google.com/spreadsheets/d/{settings.sheet_id}"
        f"/export?format=csv&gid={gid}"
    )
    logger.info("Reading sheet: %s", url)
    try:
        df = pd.read_csv(url, header=0, dtype=str)
    except Exception as e:
        logger.error("Failed to read sheet gid=%s: %s", gid, e)
        return None

    rename = {c: HEADER_MAP[c] for c in df.columns if c in HEADER_MAP}
    return df.rename(columns=rename)


def _row_to_tour(row, nguon: str) -> Tour | None:
    ten_tour = str(row.get("ten_tour") or "").strip()
    if not ten_tour or ten_tour.lower() in ("nan", "tên tour"):
        return None

    gia_raw = str(row.get("gia_raw") or "").strip()
    gia = parse_price(gia_raw)
    thoi_gian = str(row.get("thoi_gian") or "").strip()
    link_url = str(row.get("link_url") or "").strip()
    if not link_url:
        link_url = str(row.get("link_raw") or "").strip()

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


def import_sheet_tab(nguon: str, gid: str, replace: bool = False) -> int:
    """Import one sheet tab into DB. Returns number of rows processed."""
    df = _load_sheet(gid)
    if df is None or df.empty:
        return 0

    db = SessionLocal()
    count = 0
    try:
        if replace:
            deleted = db.query(Tour).filter(Tour.nguon == nguon).delete()
            db.commit()
            logger.info("Removed %s existing %s tours", deleted, nguon)

        existing_by_ma = {
            t.ma_tour: t
            for t in db.query(Tour).filter(Tour.nguon == nguon, Tour.ma_tour != "").all()
        }
        existing_by_name = {
            (t.ten_tour, t.cong_ty): t
            for t in db.query(Tour).filter(Tour.nguon == nguon).all()
        }

        pending = 0
        for _, row in df.iterrows():
            tour = _row_to_tour(row, nguon)
            if not tour:
                continue

            existing = None
            if tour.ma_tour:
                existing = existing_by_ma.get(tour.ma_tour)
            if not existing:
                existing = existing_by_name.get((tour.ten_tour, tour.cong_ty))

            if existing:
                for field in (
                    "cong_ty", "thi_truong", "tuyen_tour", "ten_tour", "lich_trinh",
                    "diem_kh", "thoi_gian", "gia_raw", "gia", "lich_kh", "link_url",
                    "ma_tour", "khach_san", "hang_khong", "so_ngay", "phan_khuc",
                ):
                    setattr(existing, field, getattr(tour, field))
            else:
                db.add(tour)
                if tour.ma_tour:
                    existing_by_ma[tour.ma_tour] = tour
                existing_by_name[(tour.ten_tour, tour.cong_ty)] = tour

            count += 1
            pending += 1
            if pending >= BATCH_SIZE:
                db.commit()
                pending = 0
                logger.info("Imported %s rows so far for %s...", count, nguon)

        db.commit()
        logger.info("Imported %s tours from %s (gid=%s)", count, nguon, gid)
    except Exception:
        db.rollback()
        logger.exception("Import failed for %s", nguon)
        raise
    finally:
        db.close()
    return count


def import_all_sheets(replace: bool = False) -> dict[str, int]:
    results: dict[str, int] = {}
    for nguon, gid in SHEET_SOURCES:
        try:
            results[nguon] = import_sheet_tab(nguon, gid, replace=replace)
        except Exception as e:
            logger.error("Skipping %s after error: %s", nguon, e)
            results[nguon] = 0
    return results


def import_if_empty() -> None:
    """Background-safe import: only runs when DB has no tours."""
    try:
        if tour_count() == 0:
            logger.info("Database empty — starting sheet import...")
            results = import_all_sheets()
            logger.info("Sheet import finished: %s", results)
        else:
            logger.info("Database has %s tours — skip import", tour_count())
    except Exception:
        logger.exception("Background sheet import failed")


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
    elif "--import-all" in sys.argv or "--import-sheet" in sys.argv:
        replace = "--replace" in sys.argv
        import_all_sheets(replace=replace)
        print("Seed completed.")
    else:
        print(f"Database has {tour_count()} tours.")
        print("Use --users-only, --import-all, or rely on background import on startup.")
        print("Seed completed.")
