"""Ghi extra scraper vào 1 tab Google Sheet CHUNG (per-source replace).

Mỗi lần 1 site chạy → CHỈ thay rows của site đó (xoá rows cột "nguồn" == source_key,
append rows mới), KHÔNG đụng rows của site khác. Không lưu DB — user tự merge sang Main.

Tab chung dùng cùng SHEET_ID với findtourgo; gid lấy từ env `OTA_EXTRA_SHEET_GID`.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

# Dùng chung spreadsheet với findtourgo.
from scrapers.findtourgo_scraper import SHEET_ID

# Header tab chung — các cột chuẩn (trùng STANDARD_COLUMNS của site) + cột "nguồn" cuối.
EXTRA_SHEET_HEADER = [
    "Tên Công Ty",     # cong_ty
    "Thị trường",      # thi_truong
    "Tuyến tour",      # tuyen_tour
    "Tên Tour",        # ten_tour
    "Lịch trình",      # lich_trinh
    "Điểm khởi hành",  # diem_kh
    "Thời gian",       # thoi_gian
    "Giá",             # gia
    "Lịch khởi hành",  # lich_kh
    "Link",            # link_url (J)
    "Hàng không",      # hang_khong (K)
    "Khách sạn",       # khach_san  (L)
    "Mã tour",         # ma_tour    (M)
    "Nguồn",           # nguon (source_key) — cột cuối phân biệt site
]

# Thứ tự field df → cột (khớp EXTRA_SHEET_HEADER, trừ cột "Nguồn" do writer gán).
_DF_FIELDS = [
    "cong_ty",
    "thi_truong",
    "tuyen_tour",
    "ten_tour",
    "lich_trinh",
    "diem_kh",
    "thoi_gian",
    "gia",
    "lich_kh",
    "link_url",
    "hang_khong",   # K
    "khach_san",    # L
    "ma_tour",      # M
]
_NGUON_COL_IDX = len(_DF_FIELDS)  # cột "Nguồn" = index 13 (cột thứ 14)
_LINK_FIELD_IDX = _DF_FIELDS.index("link_url")  # cột "Link" gốc = index 9 (cột J)
# Copy thêm link sang cột Z (index 25) — đồng bộ vị trí link với tab Main/Vietravel
# (link thô ở cột Z), tiện merge. Mở rộng tab tới 26 cột A..Z.
COL_LINK_Z = 25
_NUM_COLS = 26
EXTRA_SHEET_HEADER = EXTRA_SHEET_HEADER + [""] * (_NUM_COLS - len(EXTRA_SHEET_HEADER))
EXTRA_SHEET_HEADER[COL_LINK_Z] = "Link"


def _extra_sheet_gid() -> int:
    raw = (os.getenv("OTA_EXTRA_SHEET_GID") or "").strip()
    if not raw:
        raise RuntimeError(
            "Chưa cấu hình OTA_EXTRA_SHEET_GID — tạo 1 tab trong Google Sheet chung "
            "rồi đặt biến môi trường OTA_EXTRA_SHEET_GID = gid của tab đó."
        )
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"OTA_EXTRA_SHEET_GID không hợp lệ (phải là số gid): {raw!r}")


def _worksheet(gid: int):
    from scrapers.findtourgo_scraper import _get_gspread_client

    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.get_worksheet_by_id(gid)
    if ws is None:
        raise ValueError(f"Không tìm thấy tab gid={gid} trong sheet chung")
    return ws


def _df_row_to_sheet(row: pd.Series, source_key: str) -> list[str]:
    out = [""] * _NUM_COLS
    for i, field in enumerate(_DF_FIELDS):
        val = row.get(field, "")
        out[i] = "" if val is None else str(val)
    out[_NGUON_COL_IDX] = source_key
    out[COL_LINK_Z] = out[_LINK_FIELD_IDX]  # copy link sang cột Z (cột link thứ 2)
    return out


def write_extra_source(df: pd.DataFrame, source_key: str) -> dict[str, Any]:
    """PER-SOURCE REPLACE trong tab chung:
      1. Đọc toàn bộ tab (get_all_values). Header dòng 1 (gồm cột "Nguồn").
      2. Bỏ các rows có cột nguồn == source_key (giữ rows site khác).
      3. Append rows từ df (set cột nguồn = source_key).
      4. Ghi lại toàn bộ tab (clear + update).

    Robust: chưa có header → tạo header chuẩn. EXTRA_SHEET_GID chưa set → raise rõ.
    """
    if not source_key:
        raise ValueError("source_key (nguồn) không được rỗng")

    gid = _extra_sheet_gid()
    ws = _worksheet(gid)

    try:
        existing = ws.get_all_values()
    except Exception:
        existing = []

    # Giữ lại rows của site khác (cột nguồn != source_key). Header tự dựng lại chuẩn.
    kept: list[list[str]] = []
    if existing and len(existing) > 1:
        for row in existing[1:]:
            padded = (row + [""] * _NUM_COLS)[:_NUM_COLS]
            cur_nguon = (padded[_NGUON_COL_IDX] or "").strip()
            if cur_nguon == source_key:
                continue  # rows cũ của chính site này → thay
            kept.append(padded)

    # Rows mới từ df.
    new_rows: list[list[str]] = []
    if df is not None and not df.empty:
        for _, r in df.iterrows():
            new_rows.append(_df_row_to_sheet(r, source_key))

    out_rows = [list(EXTRA_SHEET_HEADER)] + kept + new_rows

    ws.clear()
    ws.update(out_rows, value_input_option="USER_ENTERED")

    return {
        "gid": gid,
        "source_key": source_key,
        "rows_written_for_source": len(new_rows),
        "rows_kept_other_sources": len(kept),
        "total_rows": len(out_rows) - 1,
    }
