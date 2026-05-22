#!/usr/bin/env python3
"""
Seed initial data:
  1. Create default admin user
  2. (Optional) Import existing Google Sheet data into DB
"""
from __future__ import annotations

import sys

from database import SessionLocal, init_db
from models import User
from api.auth import hash_password


def create_default_users():
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
                print(f"Created user: {u['username']} / {u['password']}")
            else:
                print(f"User already exists: {u['username']}")
        db.commit()
    finally:
        db.close()


def import_from_sheet():
    """Import main competitor sheet into DB as initial data."""
    import pandas as pd
    from config import settings
    from database import SessionLocal
    from models import Tour
    import re

    sheet_url = (
        f"https://docs.google.com/spreadsheets/d/{settings.sheet_id}"
        f"/export?format=csv&gid={settings.gid_main}"
    )
    print(f"Importing from: {sheet_url}")
    try:
        df = pd.read_csv(sheet_url, header=0, dtype=str)
    except Exception as e:
        print(f"Failed to read sheet: {e}")
        return

    cols = list(df.columns)
    POS_MAP = {0: "cong_ty", 1: "thi_truong", 2: "tuyen_tour", 3: "ten_tour",
               4: "lich_trinh", 5: "diem_kh", 6: "thoi_gian", 7: "gia_raw", 8: "lich_kh"}
    rmap = {cols[i]: name for i, name in POS_MAP.items() if i < len(cols)}
    for i, c in enumerate(cols):
        if str(c).strip().lower() == "link" and i >= 10:
            rmap[c] = "link_url"
            break
    df = df.rename(columns=rmap)

    def parse_price(v):
        if not v or str(v).strip() in ("", "nan"): return None
        cleaned = re.sub(r"[^\d]", "", str(v))
        if not cleaned: return None
        val = float(cleaned)
        return val if val > 0 else None

    def parse_ngay(v):
        if not v: return None
        s = str(v).strip().lower()
        m = re.search(r"(?<!\d)(\d{1,2})\s*n", s)
        if m:
            d = float(m.group(1))
            return d if 0 < d <= 45 else None
        return None

    def segment(gia):
        if not gia: return "Chưa có giá"
        if gia < 2e6: return "Budget (< 2tr)"
        if gia < 5e6: return "Mid (2–5tr)"
        if gia < 15e6: return "Premium (5–15tr)"
        return "Luxury (> 15tr)"

    db = SessionLocal()
    added = 0
    try:
        for _, row in df.iterrows():
            ten_tour = str(row.get("ten_tour") or "").strip()
            if not ten_tour or ten_tour.lower() in ("nan", "tên tour"):
                continue
            gia = parse_price(row.get("gia_raw", ""))
            tg = str(row.get("thoi_gian") or "").strip()
            tour = Tour(
                cong_ty=str(row.get("cong_ty") or "").strip(),
                thi_truong=str(row.get("thi_truong") or "").strip(),
                tuyen_tour=str(row.get("tuyen_tour") or "").strip(),
                ten_tour=ten_tour,
                lich_trinh=str(row.get("lich_trinh") or "").strip(),
                diem_kh=str(row.get("diem_kh") or "").strip(),
                thoi_gian=tg,
                gia_raw=str(row.get("gia_raw") or "").strip(),
                gia=gia,
                lich_kh=str(row.get("lich_kh") or "").strip(),
                link_url=str(row.get("link_url") or "").strip(),
                so_ngay=parse_ngay(tg),
                phan_khuc=segment(gia),
                nguon="Main",
            )
            db.add(tour)
            added += 1
        db.commit()
        print(f"Imported {added} tours from main sheet")
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
    create_default_users()
    if "--import-sheet" in sys.argv:
        import_from_sheet()
    print("Seed completed.")
