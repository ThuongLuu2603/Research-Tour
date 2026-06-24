"""
Ghi chú / nhận định của chuyên viên theo DÒNG (segment) — bền qua mỗi lần dựng lại báo cáo.

Vấn đề: Báo cáo BGĐ (CI + So sánh đối thủ) được DỰNG LẠI từ dữ liệu mỗi ngày (snapshot
auto) hoặc khi bấm 'Làm mới'. Ghi chú tay nhúng trong HTML vì thế bị mất, dù tuyến đó
không đổi (chỉ đổi % / giá) hay chỉ đổi vị trí lên/xuống trong khung.

Giải pháp: lưu ghi chú theo KHÓA DÒNG ổn định = (thị trường | tuyến | đầu KH) trong AppKv
(DB-persistent, dùng chung mọi worker). Khi dựng lại báo cáo → chèn ghi chú vào đúng dòng
theo khóa (bất kể số liệu đổi hay dòng đổi vị trí). Khi admin lưu bản sửa tay → trích ghi
chú từ các ô có data-segkey rồi cập nhật kho.

Mỗi ô Ghi chú render kèm data-segkey để khi parse HTML (admin vừa lưu) map lại đúng khóa.
"""
from __future__ import annotations

import html as _html
import json
import re

_NOTES_KEY = "report_row_notes"
_WS = re.compile(r"\s+")
_EMPTY = re.compile(r"<[^>]+>|&nbsp;|\s")


def _norm(s) -> str:
    return _WS.sub(" ", (str(s) if s is not None else "").strip()).lower()


def seg_key(thi_truong, tuyen_tour, diem_kh) -> str:
    """Khóa dòng ổn định cho 1 segment (không phụ thuộc số liệu/vị trí)."""
    return "|".join(_norm(x) for x in (thi_truong, tuyen_tour, diem_kh))


def get_notes(db) -> dict:
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _NOTES_KEY).first()
    if not row or not row.value_json:
        return {}
    try:
        d = json.loads(row.value_json)
        return d if isinstance(d, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def save_notes(db, notes: dict) -> None:
    from models import AppKv
    payload = json.dumps(notes or {}, ensure_ascii=False)
    row = db.query(AppKv).filter(AppKv.key == _NOTES_KEY).first()
    if row:
        row.value_json = payload
    else:
        db.add(AppKv(key=_NOTES_KEY, value_json=payload))
    db.commit()


def note_cell(key: str, notes: dict, *, extra_style: str = "") -> str:
    """Render ô <td> Ghi chú: mang data-segkey + nội dung đã lưu (nếu có)."""
    val = (notes or {}).get(key) or ""
    style = f" style='{extra_style}'" if extra_style else ""
    return f"<td class='note' data-segkey=\"{_html.escape(key, quote=True)}\"{style}>{val}</td>"


def extract_notes_from_html(html_text: str, base: dict | None = None) -> dict:
    """
    Trích ghi chú từ mọi phần tử có data-segkey trong HTML admin vừa lưu, gộp vào `base`.
    Ô trống → xoá khỏi kho; ô có nội dung → ghi đè. Lỗi parse → trả `base` nguyên trạng.
    """
    out = dict(base or {})
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_text or "", "lxml")
        for el in soup.select("[data-segkey]"):
            key = (el.get("data-segkey") or "").strip()
            if not key:
                continue
            inner = el.decode_contents().strip()
            if _EMPTY.sub("", inner) == "":
                out.pop(key, None)
            else:
                out[key] = inner
    except Exception:  # noqa: BLE001 — parse hỏng thì giữ kho cũ, không làm mất dữ liệu
        return dict(base or {})
    return out
