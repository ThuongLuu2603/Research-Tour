"""Đồng bộ tour Research Grid ↔ Google Sheet."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import datetime

from config import settings
from models import Tour
from tour_identity import compute_content_hash, compute_external_id
from data_sanitize import clean_text

logger = logging.getLogger(__name__)

# Tránh xóa hàng loạt khi Sheet trống / lỗi scrape
MIRROR_PRUNE_MIN_SYNCED = 10


def _clean_field(value: str | None) -> str:
    return clean_text(value, max_len=256)

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
    from link_utils import normalize_tour_link
    return normalize_tour_link(cell)


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


def _scrape_row_to_fields(row) -> dict | None:
    """DataFrame/Series row từ scraper Vietravel → fields chuẩn."""
    from classification import resolve_company_name, resolve_departure_point
    from link_utils import normalize_tour_link

    ten = str(row.get("ten_tour") or "").strip()
    if not ten or ten.lower() in ("tên tour", "nan"):
        return None
    gia_col = "gia" if "gia" in row.index else "gia_tu" if "gia_tu" in row.index else None
    gia_raw = str(row.get(gia_col) or "") if gia_col else ""
    link = normalize_tour_link(str(row.get("link_url") or "").strip())
    return {
        "cong_ty": resolve_company_name(str(row.get("cong_ty") or "").strip()),
        "thi_truong": str(row.get("thi_truong") or "").strip(),
        "tuyen_tour": str(row.get("tuyen_tour") or "").strip(),
        "ten_tour": ten,
        "lich_trinh": str(row.get("lich_trinh") or "").strip(),
        "diem_kh": resolve_departure_point(str(row.get("diem_kh") or "").strip()),
        "thoi_gian": str(row.get("thoi_gian") or "").strip(),
        "gia_raw": gia_raw,
        "gia": _parse_price(gia_raw),
        "lich_kh": str(row.get("lich_kh") or "").strip(),
        "link_url": link,
        "ma_tour": str(row.get("ma_tour") or row.get("page_code") or "").strip(),
        "khach_san": _clean_field(str(row.get("khach_san") or "")),
        "hang_khong": _clean_field(str(row.get("hang_khong") or "")),
        "dong_tour": str(row.get("dong_tour") or "").strip(),
    }


def _row_to_fields(row: list[str], *, nguon: str = "") -> dict | None:
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
    # Main: cột B/C (thị trường, tuyến) không import — gán bằng quy tắc tuyến sau.
    sheet_tt = "" if nguon == "Main" else (row[1] if len(row) > 1 else "").strip()
    sheet_route = "" if nguon == "Main" else (row[2] if len(row) > 2 else "").strip()
    return {
        "cong_ty": (row[0] if len(row) > 0 else "").strip(),
        "thi_truong": sheet_tt,
        "tuyen_tour": sheet_route,
        "ten_tour": ten,
        "lich_trinh": (row[4] if len(row) > 4 else "").strip(),
        "diem_kh": (row[5] if len(row) > 5 else "").strip(),
        "thoi_gian": (row[6] if len(row) > 6 else "").strip(),
        "gia_raw": str(gia_raw).strip(),
        "gia": _parse_price(gia_raw),
        "lich_kh": (row[8] if len(row) > 8 else "").strip(),
        "link_url": link,
        "ma_tour": (row[12] if len(row) > 12 else "").strip(),
        "khach_san": _clean_field(row[10] if len(row) > 10 else ""),
        "hang_khong": _clean_field(row[11] if len(row) > 11 else ""),
        # Dòng tour ở cột O (index 14) — chỉ tab Vietravel có; Main không có cột này.
        **({"dong_tour": (row[14] if len(row) > 14 else "").strip()} if nguon == "Vietravel" else {}),
    }


def _needs_route_reclassification(tour: Tour, fields: dict) -> bool:
    """Chỉ chạy quy tắc tuyến khi tour chưa có phân loại hoặc tên/lịch trình đổi."""
    # Admin khóa tay + tên KHÔNG đổi → giữ phân loại thủ công, không chạy lại quy tắc.
    if getattr(tour, "manual_locked", False) and (fields.get("ten_tour") or "").strip() == (tour.ten_tour or "").strip():
        return False
    if not (tour.tuyen_tour or "").strip() or not (tour.thi_truong or "").strip():
        return True
    if (fields.get("ten_tour") or "").strip() != (tour.ten_tour or "").strip():
        return True
    if (fields.get("lich_trinh") or "").strip() != (tour.lich_trinh or "").strip():
        return True
    return False


def _phan_khuc_inputs_changed(tour: Tour, fields: dict) -> bool:
    if not (tour.phan_khuc or "").strip() or tour.phan_khuc == "Chưa có giá":
        return True
    if fields.get("gia") != tour.gia:
        return True
    if (fields.get("thoi_gian") or "").strip() != (tour.thoi_gian or "").strip():
        return True
    mk = (fields.get("thi_truong") or "").strip()
    rt = (fields.get("tuyen_tour") or "").strip()
    if mk and mk != (tour.thi_truong or "").strip():
        return True
    if rt and rt != (tour.tuyen_tour or "").strip():
        return True
    return False


def _build_tour_lookup(db, nguon: str) -> dict[str, dict[str, Tour]]:
    """Load chỉ các cột cần cho matching + content_hash — giảm Egress ~50%.
    Các cột nặng (lich_trinh, analyst_note, flagged, phan_khuc, thoi_gian, gia)
    không cần thiết ở bước lookup; chỉ dùng khi _apply_fields_to_tour ghi đè.
    """
    from sqlalchemy import or_
    from sqlalchemy.orm import load_only

    q = db.query(Tour).options(load_only(
        Tour.id,
        Tour.external_id,
        Tour.nguon,
        Tour.ma_tour,
        Tour.link_url,
        Tour.ten_tour,
        # lich_trinh, phan_khuc, gia, thoi_gian, analyst_note, flagged
        # → KHÔNG load ở đây; SQLAlchemy lazy-load khi _apply_fields_to_tour truy cập
        Tour.thi_truong,
        Tour.tuyen_tour,
        Tour.content_hash,
        Tour.sheet_source,
    ))
    if nguon == "Main":
        q = q.filter(or_(Tour.nguon == nguon, Tour.ma_tour != "", Tour.link_url != ""))
    else:
        q = q.filter(Tour.nguon == nguon)

    lookup: dict[str, dict[str, Tour]] = {
        "external": {},
        "source_ma": {},
        "source_link": {},
        "source_ten": {},
        "any_ma": {},
        "any_link": {},
    }
    for tour in q.order_by(Tour.id).all():
        _remember_tour_lookup(lookup, tour)
    return lookup


def _remember_tour_lookup(lookup: dict[str, dict[str, Tour]], tour: Tour) -> None:
    ext = (tour.external_id or "").strip()
    ma = (tour.ma_tour or "").strip()
    link = (tour.link_url or "").strip()
    ten = (tour.ten_tour or "").strip()
    source = (tour.nguon or "").strip()
    if ext:
        lookup["external"].setdefault(ext, tour)
    if ma:
        lookup["source_ma"].setdefault(f"{source}|{ma}", tour)
        lookup["any_ma"].setdefault(ma, tour)
    if link:
        lookup["source_link"].setdefault(f"{source}|{link}", tour)
        lookup["any_link"].setdefault(link, tour)
        lookup["any_link"].setdefault(link.split("?")[0], tour)
    if ten:
        lookup["source_ten"].setdefault(f"{source}|{ten}", tour)


def _find_db_tour(
    db,
    nguon: str,
    fields: dict,
    external_id: str,
    lookup: dict[str, dict[str, Tour]] | None = None,
) -> Tour | None:
    if lookup is not None:
        tour = lookup["external"].get(external_id)
        if tour:
            return tour
        ma = fields.get("ma_tour") or ""
        link = fields.get("link_url") or ""
        ten = fields.get("ten_tour") or ""
        if ma:
            tour = lookup["source_ma"].get(f"{nguon}|{ma}")
            if tour:
                return tour
        if link:
            tour = lookup["source_link"].get(f"{nguon}|{link}")
            if tour:
                return tour
        if ten:
            tour = lookup["source_ten"].get(f"{nguon}|{ten}")
            if tour:
                return tour
        if nguon != "Main":
            return None
        if ma:
            tour = lookup["any_ma"].get(ma)
            if tour:
                return tour
        if link:
            for needle in (link, link.split("?")[0]):
                if not needle:
                    continue
                tour = lookup["any_link"].get(needle)
                if tour:
                    return tour
        return None

    tour = db.query(Tour).filter(Tour.external_id == external_id).first()
    if tour:
        return tour

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
        t = db.query(Tour).filter(Tour.nguon == nguon, Tour.ten_tour == ten).first()
        if t:
            return t

    # Sheet Main là nguồn chuẩn — cập nhật tour trùng mã/link ở nguồn khác (vd. FindTourGo)
    if nguon != "Main":
        return None
    if ma:
        t = db.query(Tour).filter(Tour.ma_tour == ma).first()
        if t:
            return t
    if link:
        for needle in (link, link.split("?")[0]):
            if not needle:
                continue
            t = db.query(Tour).filter(Tour.link_url == needle).first()
            if t:
                return t
    return None


def _apply_fields_to_tour(
    tour: Tour,
    fields: dict,
    nguon: str,
    now: datetime,
    *,
    preserve_nguon: bool = False,
    preserve_analyst: bool = True,
    preserve_classification: bool = False,
    external_id: str = "",
    sheet_row: int | None = None,
) -> None:
    from classification import classify_route_fields, resolve_company_name, resolve_departure_point
    from seed import parse_ngay

    note = tour.analyst_note
    flagged = tour.flagged

    # Khóa thủ công (admin) + tên KHÔNG đổi → giữ Thị trường/Tuyến/Thời gian; đổi tên = tour mới → bỏ khóa.
    _old_name = (tour.ten_tour or "").strip()
    _new_name = (fields.get("ten_tour") or "").strip()
    _name_changed = bool(_old_name) and _new_name != _old_name
    _was_locked = bool(getattr(tour, "manual_locked", False))
    locked = _was_locked and not _name_changed
    if _was_locked and _name_changed:
        tour.manual_locked = False

    if locked:
        # Chỉ tính lại phân khúc khi GIÁ đổi (thời gian/tuyến giữ nguyên do khóa).
        phan_khuc_dirty = (not (tour.phan_khuc or "").strip()) or (fields.get("gia") != tour.gia)
    else:
        phan_khuc_dirty = _phan_khuc_inputs_changed(tour, fields)

    # STICKY: chỉ overwrite cong_ty khi nguồn có giá trị mới (sau resolve alias).
    # Nếu sheet/scrape row có cong_ty rỗng → giữ giá trị cũ trên DB. Tránh
    # wipe khi 1 lần sync lỗi extract / cột A trống / Vietravel block thiếu label.
    new_cong_ty = resolve_company_name(fields.get("cong_ty") or "")
    if new_cong_ty and new_cong_ty.strip():
        tour.cong_ty = new_cong_ty[:256]
    # else: giữ tour.cong_ty hiện tại
    tour.ten_tour = fields["ten_tour"][:512]
    tour.lich_trinh = fields["lich_trinh"]
    if (preserve_classification or locked) and (tour.thi_truong or tour.tuyen_tour):
        fields = {
            **fields,
            "thi_truong": tour.thi_truong or "",
            "tuyen_tour": tour.tuyen_tour or "",
        }
    if nguon in ("Main", "Vietravel"):
        mk = (fields.get("thi_truong") or "").strip()
        rt = (fields.get("tuyen_tour") or "").strip()
        if not preserve_classification and not locked and not mk and not rt:
            mk, rt = classify_route_fields(tour.ten_tour, tour.lich_trinh)
        tour.thi_truong = mk[:128]
        tour.tuyen_tour = rt[:256]
        fields = {**fields, "thi_truong": tour.thi_truong, "tuyen_tour": tour.tuyen_tour}
    else:
        tour.thi_truong = fields["thi_truong"][:128]
        tour.tuyen_tour = fields["tuyen_tour"][:256]
    # STICKY: chỉ overwrite khi scrape extract được giá trị mới.
    # Nếu rỗng/scrape lỗi → giữ value cũ (tránh xóa data quý của user).
    new_diem_kh = resolve_departure_point(fields.get("diem_kh") or "")
    if new_diem_kh.strip():
        tour.diem_kh = new_diem_kh[:256]
    # else: giữ tour.diem_kh hiện tại

    if not locked:
        new_thoi_gian = (fields.get("thoi_gian") or "").strip()
        if new_thoi_gian:
            # Chuẩn hóa về dạng NĐ (7N6Đ) khi khớp alias; giữ raw nếu không khớp.
            from classification import normalize_duration_text
            norm_tg, _ = normalize_duration_text(new_thoi_gian, None)
            tour.thoi_gian = (norm_tg or new_thoi_gian)[:64]
        # else: giữ tour.thoi_gian hiện tại
    tour.gia_raw = fields["gia_raw"][:64]
    tour.gia = fields["gia"]
    tour.lich_kh = fields["lich_kh"]
    if fields["link_url"]:
        tour.link_url = fields["link_url"]
    if fields["ma_tour"]:
        tour.ma_tour = fields["ma_tour"][:64]
    tour.khach_san = _clean_field(fields.get("khach_san"))
    tour.hang_khong = _clean_field(fields.get("hang_khong"))
    new_dong_tour = (fields.get("dong_tour") or "").strip()
    if new_dong_tour:  # STICKY: chỉ ghi khi scrape có giá trị (1 lần quét lỗi không xoá tier cũ)
        tour.dong_tour = new_dong_tour[:64]
    if not locked:
        # STICKY parallel với thoi_gian: chỉ recompute so_ngay khi nguồn có
        # thoi_gian mới (parse_ngay rỗng = None → wipe so_ngay khiến phân khúc lỗi).
        if (fields.get("thoi_gian") or "").strip():
            tour.so_ngay = parse_ngay(fields["thoi_gian"])
    # Vietravel: phân_khuc = dòng tour. STICKY khi không có dòng_tour mới — tránh
    # tour bị mất nhãn nếu 1 lần scrape không parse được tourLineId (vd HTML đổi).
    # Trước đây: phan_khuc_dirty=True → phan_khuc="" rồi mới gán lại nếu có dong_tour
    # mới; nếu không có thì rỗng vĩnh viễn. Giờ: chỉ reset rồi GÁN khi có giá trị
    # mới — không có → giữ nguyên giá trị cũ. Áp dụng cho mọi nguồn.
    if nguon == "Vietravel":
        if (tour.dong_tour or "").strip():
            tour.phan_khuc = (tour.dong_tour or "").strip()[:64]
        # else: giữ phan_khuc cũ (sticky)
    elif phan_khuc_dirty:
        # Non-VTR: gía/thị trường/tuyến đổi → cần recompute giá. Đánh dấu rỗng để
        # recompute_segments_for_sync() fill lại sau.
        tour.phan_khuc = ""
    if not preserve_nguon:
        tour.nguon = nguon
    if external_id:
        tour.external_id = external_id[:128]
    tour.sheet_source = nguon
    if sheet_row is not None:
        tour.sheet_row = sheet_row
    tour.content_hash = compute_content_hash(fields)
    tour.last_synced_at = now
    if preserve_analyst:
        tour.analyst_note = note
        tour.flagged = flagged
    tour.updated_at = now
    from tour_search import update_tour_derived_fields

    update_tour_derived_fields(tour)


def _create_tour_from_fields(fields: dict, nguon: str, now: datetime) -> Tour:
    tour = Tour(created_at=now)
    _apply_fields_to_tour(tour, fields, nguon, now)
    return tour


def _delete_tour_ids(db, tour_ids: list[int]) -> int:
    if not tour_ids:
        return 0
    from models import TourOverride

    db.query(TourOverride).filter(TourOverride.tour_id.in_(tour_ids)).delete(
        synchronize_session=False
    )
    db.query(Tour).filter(Tour.id.in_(tour_ids)).delete(synchronize_session=False)
    try:
        from tour_search import after_tours_persisted

        after_tours_persisted(db, tour_ids, deleted=True)
    except Exception:
        pass
    return len(tour_ids)


def _prune_stale_tours_for_source(db, nguon: str, synced_tour_ids: set[int]) -> int:
    """Xóa tour trong DB (nguon) không còn trên tab Sheet sau lần sync vừa rồi."""
    from models import TourOverride

    if len(synced_tour_ids) < MIRROR_PRUNE_MIN_SYNCED:
        logger.warning(
            "Mirror prune skipped for %s: only %s tours on sheet (min %s)",
            nguon,
            len(synced_tour_ids),
            MIRROR_PRUNE_MIN_SYNCED,
        )
        return 0

    # Lấy hết id của nguồn rồi trừ tập đã sync TRONG PYTHON — tránh NOT IN (8000+ literal)
    # (CockroachDB chạy query đó rất chậm/treo). Chỉ tải cột id (nhẹ).
    synced = {int(i) for i in synced_tour_ids}
    stale_ids = [
        tid
        for (tid,) in db.query(Tour.id).filter(Tour.nguon == nguon).all()
        if tid not in synced
    ]
    if not stale_ids:
        return 0

    deleted = 0
    for i in range(0, len(stale_ids), 500):  # xóa theo lô — IN list bị chặn nhỏ
        deleted += _delete_tour_ids(db, stale_ids[i:i + 500])
        db.commit()
    logger.info("Mirror prune %s: removed %s stale tours", nguon, deleted)
    return deleted


def purge_nguon_from_db(db, nguon: str) -> int:
    """Xóa toàn bộ tour một nguồn khỏi DB (vd. FindTourGo chỉ lưu Sheet)."""
    from models import Tour
    from db_retry import run_with_retry

    def _do():
        db.rollback()  # re-query ids mỗi lần thử → idempotent, retry an toàn
        ids = [tid for (tid,) in db.query(Tour.id).filter(Tour.nguon == nguon).all()]
        if not ids:
            return 0
        n = _delete_tour_ids(db, ids)
        db.commit()
        return n

    deleted = run_with_retry(_do, db=db, label="purge-nguon")
    logger.info("Purged %s tours with nguon=%s from DB", deleted, nguon)
    return deleted


def _merge_dataframe_to_db_locked(
    db,
    df,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
    progress: Callable[[int, str], None] | None = None,
    commit_batch: int = 80,
    cancel_check=None,
) -> dict:
    """Scraper → DB trước (Vietravel). Tour.id giữ nguyên khi match external_id."""
    from job_cancel import JobCancelled, raise_if_cancelled
    if hasattr(db, "expire_on_commit"):
        db.expire_on_commit = False
    from classification import _load_route_rules
    from data_sources import is_db_canonical_source, should_mirror_prune

    if not is_db_canonical_source(nguon):
        raise ValueError(f"Nguồn {nguon} không lưu DB — chỉ Sheet")
    if mirror_delete is None:
        mirror_delete = should_mirror_prune(nguon)

    from route_rule_matcher import RouteRuleMatcher

    matcher = RouteRuleMatcher(_load_route_rules()) if nguon in ("Vietravel", "Main") else None
    total = len(df)
    updated = inserted = skipped = unchanged = route_reclassified = route_preserved = 0
    synced_tour_ids: set[int] = set()
    affected_tour_ids: set[int] = set()
    lookup = _build_tour_lookup(db, nguon)
    now = datetime.utcnow()
    for idx, (_, row) in enumerate(df.iterrows()):
        fields = _scrape_row_to_fields(row)
        if not fields:
            skipped += 1
            continue
        if not fields.get("gia"):
            skipped += 1
            continue

        external_id = compute_external_id(
            nguon,
            ma_tour=fields.get("ma_tour", ""),
            link_url=fields.get("link_url", ""),
            ten_tour=fields.get("ten_tour", ""),
        )
        tour = _find_db_tour(db, nguon, fields, external_id, lookup)
        is_new = tour is None
        needs_classify = is_new or (tour is not None and _needs_route_reclassification(tour, fields))

        if matcher and needs_classify:
            mk, rt, matched, _rid = matcher.resolve(
                fields["ten_tour"],
                fields["lich_trinh"],
            )
            if matched:
                fields["thi_truong"] = mk
                fields["tuyen_tour"] = rt
            elif nguon in ("Main", "Vietravel"):
                # RULE LÀ NGUỒN CHÂN LÝ: rule không match → KHÔNG lấy classification
                # từ cột Google Sheet (tránh data sai/cũ trong sheet đè lên). Để trống
                # → tour vào panel "Chưa khớp" để admin tạo rule. Tránh case tour
                # "Trung Quốc Tân Cương" bị gán nhầm "Châu Mỹ / Bờ Tây Mỹ" từ cột sheet.
                fields["thi_truong"] = ""
                fields["tuyen_tour"] = ""
        elif not is_new and tour is not None and not needs_classify:
            fields = {
                **fields,
                "thi_truong": tour.thi_truong or "",
                "tuyen_tour": tour.tuyen_tour or "",
            }

        if is_new:
            tour = _create_tour_from_fields(fields, nguon, now)
            tour.external_id = external_id[:128]
            db.add(tour)
            db.flush()
            synced_tour_ids.add(tour.id)
            affected_tour_ids.add(tour.id)
            inserted += 1
            if needs_classify:
                route_reclassified += 1
        else:
            synced_tour_ids.add(tour.id)
            new_hash = compute_content_hash(fields)
            if tour.content_hash == new_hash and tour.sheet_source == nguon:
                unchanged += 1
                continue
            updated += 1
            affected_tour_ids.add(tour.id)
            if needs_classify:
                route_reclassified += 1
            else:
                route_preserved += 1

        _apply_fields_to_tour(
            tour,
            fields,
            nguon,
            now,
            preserve_nguon=(not is_new and tour.nguon not in ("", nguon)),
            preserve_classification=(not is_new and not needs_classify),
            external_id=external_id,
        )
        _remember_tour_lookup(lookup, tour)

        if progress and (idx % 15 == 0 or idx + 1 == total):
            pct = 65 + int(17 * (idx + 1) / max(total, 1))
            progress(pct, f"Đang lưu DB {idx + 1}/{total} (+{inserted} mới, ~{updated} cập nhật)")
        if commit_batch > 0 and (idx + 1) % commit_batch == 0:
            db.commit()
            raise_if_cancelled(cancel_check)

    # Nhịp tiến độ hậu-commit — giữ heartbeat job tươi (không bị coi là treo).
    def _beat(msg: str) -> None:
        if progress:
            try:
                progress(83, msg)
            except Exception:  # noqa: BLE001
                pass

    db.commit()
    raise_if_cancelled(cancel_check)
    _flush_search_after_commit(db, synced_tour_ids, cancel_check, _beat)

    deleted = 0
    if mirror_delete:
        _beat("Đang dọn tour không còn nguồn…")
        deleted = _prune_stale_tours_for_source(db, nguon, synced_tour_ids)
        if deleted:
            db.commit()

    phan_khuc_stats: dict | None = None
    if recompute_segments and affected_tour_ids:
        if progress:
            progress(83, "Đã lưu DB — đang tính lại phân khúc…")
        raise_if_cancelled(cancel_check)
        try:
            from pricing_segments import recompute_segments_for_sync

            phan_khuc_stats = recompute_segments_for_sync(db, affected_tour_ids, cancel_check, _beat)
        except JobCancelled:
            raise
        except Exception as e:
            logger.warning("recompute phan_khuc after %s scrape failed: %s", nguon, e)
            phan_khuc_stats = {"error": str(e)}

    # SAFETY NET — bắt tour bị clear phan_khuc nhưng recompute_segments_for_sync
    # bỏ sót (vì partial fail, hoặc tour không nằm trong affected_tour_ids do
    # baseline route thay đổi). Trước đây chỉ chạy ở merge_all_sheet_sources_to_db
    # → sync 1 nguồn lẻ (Vietravel/Main) bị "phân khúc mất tiu" trên các tour cũ.
    if recompute_segments:
        try:
            from pricing_segments import recompute_missing_phan_khuc

            missing_filled = recompute_missing_phan_khuc(db, cancel_check, _beat)
            if missing_filled:
                logger.info("recompute_missing_phan_khuc safety net: filled %d tours after %s sync", missing_filled, nguon)
                if phan_khuc_stats is None:
                    phan_khuc_stats = {}
                phan_khuc_stats["missing_filled"] = missing_filled
        except JobCancelled:
            raise
        except Exception as e:
            logger.warning("recompute_missing_phan_khuc safety net failed after %s sync: %s", nguon, e)

    if inserted or updated or deleted:
        if progress:
            progress(86, "Đang làm mới cache so sánh…")
        _post_sync_cache(db)

    out = {
        "nguon": nguon,
        "updated": updated,
        "inserted": inserted,
        "skipped": skipped,
        "unchanged": unchanged,
        "deleted": deleted,
        "synced": len(synced_tour_ids),
        "route_reclassified": route_reclassified,
        "route_preserved": route_preserved,
        "affected_tour_ids": sorted(affected_tour_ids),
    }
    if phan_khuc_stats is not None:
        out["phan_khuc"] = phan_khuc_stats
    return out


def merge_dataframe_to_db(
    db,
    df,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
    progress: Callable[[int, str], None] | None = None,
    commit_batch: int = 80,
    cancel_check=None,
) -> dict:
    from db_job_lock import tours_write_lock

    with tours_write_lock(db, f"merge_dataframe_to_db:{nguon}") as locked:
        if not locked:
            raise RuntimeError("Đang có job khác ghi dữ liệu tour. Vui lòng thử lại sau.")
        return _merge_dataframe_to_db_locked(
            db,
            df,
            nguon,
            mirror_delete=mirror_delete,
            recompute_segments=recompute_segments,
            progress=progress,
            commit_batch=commit_batch,
            cancel_check=cancel_check,
        )


def export_vietravel_tab_from_db(db) -> dict:
    """DB (nguon=Vietravel) → ghi đè tab Sheet Vietravel.
    Chỉ load đúng cột cần cho Sheet — giảm Egress đáng kể.
    """
    from sqlalchemy.orm import load_only
    from models import Tour
    from scrapers.vietravel_scraper import db_tours_to_dataframe, write_to_google_sheet

    tours = (
        db.query(Tour)
        .options(load_only(
            Tour.id,
            Tour.cong_ty,
            Tour.thi_truong,
            Tour.tuyen_tour,
            Tour.ten_tour,
            Tour.lich_trinh,
            Tour.diem_kh,
            Tour.thoi_gian,
            Tour.gia,
            Tour.gia_raw,
            Tour.lich_kh,
            Tour.link_url,
            Tour.ma_tour,
            Tour.updated_at,
        ))
        .filter(Tour.nguon == "Vietravel")
        .order_by(Tour.id)
        .all()
    )
    df = db_tours_to_dataframe(tours)
    write_to_google_sheet(df)
    return {"ok": True, "rows": len(tours)}


def _merge_sheet_source_to_db_locked(
    db,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
    force_reclassify_all: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
    commit_batch: int = 100,
    cancel_check=None,
) -> dict:
    from job_cancel import JobCancelled, raise_if_cancelled
    if hasattr(db, "expire_on_commit"):
        db.expire_on_commit = False
    from data_sources import is_db_canonical_source, should_mirror_prune

    if not is_db_canonical_source(nguon):
        raise ValueError(
            f"Tab {nguon} không đồng bộ vào DB — FindTourGo chỉ lưu trên Google Sheet"
        )
    if mirror_delete is None:
        mirror_delete = should_mirror_prune(nguon)

    from classification import _load_route_rules
    from route_rule_matcher import RouteRuleMatcher

    matcher = RouteRuleMatcher(_load_route_rules()) if nguon in ("Vietravel", "Main") else None

    ws = _worksheet(nguon)
    rows = ws.get_all_values()
    if len(rows) < 2:
        return {
            "nguon": nguon,
            "updated": 0,
            "inserted": 0,
            "skipped": 0,
            "unchanged": 0,
            "deleted": 0,
            "synced": 0,
        }

    updated = inserted = skipped = unchanged = route_reclassified = route_preserved = 0
    synced_tour_ids: set[int] = set()
    affected_tour_ids: set[int] = set()
    lookup = _build_tour_lookup(db, nguon)
    now = datetime.utcnow()
    data_rows = rows[1:]
    total_rows = len(data_rows)
    if progress_cb and total_rows:
        progress_cb(0, total_rows, f"Đang đồng bộ {nguon}: 0/{total_rows} dòng Sheet…")
    for row_num, row in enumerate(data_rows, start=1):
        row_idx = row_num + 1
        fields = _row_to_fields(row, nguon=nguon)
        if not fields:
            skipped += 1
            continue
        external_id = compute_external_id(
            nguon,
            ma_tour=fields.get("ma_tour", ""),
            link_url=fields.get("link_url", ""),
            ten_tour=fields.get("ten_tour", ""),
        )
        tour = _find_db_tour(db, nguon, fields, external_id, lookup)
        is_new = tour is None
        needs_classify = (
            is_new
            or force_reclassify_all
            or (tour is not None and _needs_route_reclassification(tour, fields))
        )

        if matcher and needs_classify:
            mk, rt, matched, _rid = matcher.resolve(
                fields["ten_tour"],
                fields["lich_trinh"],
            )
            if matched:
                fields["thi_truong"] = mk
                fields["tuyen_tour"] = rt
            elif nguon in ("Main", "Vietravel"):
                # RULE LÀ NGUỒN CHÂN LÝ: rule không match → KHÔNG lấy classification
                # từ cột Google Sheet (tránh data sai/cũ trong sheet đè lên). Để trống
                # → tour vào panel "Chưa khớp" để admin tạo rule. Tránh case tour
                # "Trung Quốc Tân Cương" bị gán nhầm "Châu Mỹ / Bờ Tây Mỹ" từ cột sheet.
                fields["thi_truong"] = ""
                fields["tuyen_tour"] = ""
        elif not is_new and tour is not None and not needs_classify:
            fields = {
                **fields,
                "thi_truong": tour.thi_truong or "",
                "tuyen_tour": tour.tuyen_tour or "",
            }

        if is_new:
            if not fields.get("gia"):
                skipped += 1
                continue
            tour = _create_tour_from_fields(fields, nguon, now)
            db.add(tour)
            db.flush()
            synced_tour_ids.add(tour.id)
            affected_tour_ids.add(tour.id)
            inserted += 1
            if needs_classify:
                route_reclassified += 1
        else:
            synced_tour_ids.add(tour.id)
            new_hash = compute_content_hash(fields)
            if tour.content_hash == new_hash and tour.sheet_source == nguon:
                unchanged += 1
                continue
            updated += 1
            affected_tour_ids.add(tour.id)
            if needs_classify:
                route_reclassified += 1
            else:
                route_preserved += 1

        _apply_fields_to_tour(
            tour,
            fields,
            nguon,
            now,
            preserve_nguon=(not is_new and tour.nguon not in ("", nguon)),
            preserve_classification=(not is_new and not needs_classify),
            external_id=external_id,
            sheet_row=row_idx,
        )
        _remember_tour_lookup(lookup, tour)

        if commit_batch > 0 and row_num % commit_batch == 0:
            db.commit()
            raise_if_cancelled(cancel_check)  # dừng sớm sau mỗi lô đã commit (không mất dữ liệu)

        if progress_cb and total_rows and (row_num % 100 == 0 or row_num == total_rows):
            progress_cb(
                row_num,
                total_rows,
                f"Đang đồng bộ {nguon}: {row_num}/{total_rows} (matcher + ghi DB)…",
            )

    # Nhịp tiến độ cho các bước HẬU-COMMIT (tsvector, prune, cache, phân khúc) — giữ heartbeat
    # job tươi để KHÔNG bị coi là treo, và để người dùng thấy tiến độ thật (không đứng im ở 100%).
    def _beat(msg: str) -> None:
        if progress_cb and total_rows:
            try:
                progress_cb(total_rows, total_rows, f"{msg} ({nguon})")
            except Exception:  # noqa: BLE001
                pass

    if progress_cb and total_rows:
        progress_cb(total_rows, total_rows, f"Đang commit & phân khúc giá ({nguon})…")
    db.commit()
    raise_if_cancelled(cancel_check)  # toàn bộ tour đã commit → dừng an toàn trước các bước nặng
    _flush_search_after_commit(db, synced_tour_ids, cancel_check, _beat)

    deleted = 0
    if mirror_delete:
        _beat("Đang dọn tour không còn trên Sheet")
        deleted = _prune_stale_tours_for_source(db, nguon, synced_tour_ids)
        if deleted:
            db.commit()

    if inserted or updated or deleted:
        _beat("Đang cập nhật cache so sánh")
        _post_sync_cache(db)

    phan_khuc_stats: dict | None = None
    if recompute_segments and affected_tour_ids:
        raise_if_cancelled(cancel_check)
        try:
            from pricing_segments import recompute_segments_for_sync

            phan_khuc_stats = recompute_segments_for_sync(db, affected_tour_ids, cancel_check, _beat)
        except JobCancelled:
            raise  # cancel phải nổi lên để dừng cả job, không nuốt thành "recompute lỗi"
        except Exception as e:
            logger.warning("recompute phan_khuc after %s sync failed: %s", nguon, e)
            phan_khuc_stats = {"error": str(e)}

    # SAFETY NET (identical to merge_sheet_source_to_db) — Vietravel scrape sync
    # cũng cần fill phan_khuc cho tour bị clear nhưng recompute_segments_for_sync
    # bỏ sót (do baseline route thay đổi hoặc partial fail). Trước đây thiếu safety
    # net ở path này → user thấy "tour update không có phân khúc" sau Vietravel sync.
    if recompute_segments:
        try:
            from pricing_segments import recompute_missing_phan_khuc

            missing_filled = recompute_missing_phan_khuc(db, cancel_check, _beat)
            if missing_filled:
                logger.info("recompute_missing_phan_khuc safety net: filled %d tours after %s scrape sync", missing_filled, nguon)
                if phan_khuc_stats is None:
                    phan_khuc_stats = {}
                phan_khuc_stats["missing_filled"] = missing_filled
        except JobCancelled:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("recompute_missing_phan_khuc safety net failed after %s scrape sync: %s", nguon, e)

    logger.info(
        "Sheet sync %s: inserted=%s updated=%s unchanged=%s skipped=%s deleted=%s synced=%s "
        "route_reclassified=%s route_preserved=%s",
        nguon,
        inserted,
        updated,
        unchanged,
        skipped,
        deleted,
        len(synced_tour_ids),
        route_reclassified,
        route_preserved,
    )
    out = {
        "nguon": nguon,
        "updated": updated,
        "inserted": inserted,
        "skipped": skipped,
        "unchanged": unchanged,
        "deleted": deleted,
        "synced": len(synced_tour_ids),
        "route_reclassified": route_reclassified,
        "route_preserved": route_preserved,
        "affected_tour_ids": sorted(affected_tour_ids),
    }
    if phan_khuc_stats is not None:
        out["phan_khuc"] = phan_khuc_stats
    return out


def _flush_search_after_commit(db, tour_ids: set[int] | list[int], cancel_check=None, progress=None) -> None:
    """Sau commit — cập nhật tsvector GIN (PostgreSQL)."""
    from tour_search import sync_search_tsv_for_ids

    _ = db
    ids = [int(i) for i in tour_ids if i]
    if ids:
        sync_search_tsv_for_ids(ids, cancel_check, progress)


def _post_sync_cache(db) -> None:
    try:
        from compare_cache import invalidate_compare_cache, prewarm_compare_cache

        invalidate_compare_cache()
        prewarm_compare_cache(db)
        # Bỏ refresh_segment_mv() — MV vô dụng (không ai đọc) và REFRESH treo trên CockroachDB.
    except Exception as e:
        logger.warning("post-sync cache refresh failed: %s", e)


def merge_sheet_source_to_db(
    db,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
    force_reclassify_all: bool = False,
    progress_cb: Callable[[int, int, str], None] | None = None,
    commit_batch: int = 100,
    cancel_check=None,
) -> dict:
    from db_job_lock import tours_write_lock

    with tours_write_lock(db, f"merge_sheet_source_to_db:{nguon}") as locked:
        if not locked:
            raise RuntimeError("Đang có job khác ghi dữ liệu tour. Vui lòng thử lại sau.")
        return _merge_sheet_source_to_db_locked(
            db,
            nguon,
            mirror_delete=mirror_delete,
            recompute_segments=recompute_segments,
            force_reclassify_all=force_reclassify_all,
            progress_cb=progress_cb,
            commit_batch=commit_batch,
            cancel_check=cancel_check,
        )


def merge_all_sheets_to_db(db) -> dict:
    """Sheet → DB: chỉ Main + Vietravel (FindTourGo bỏ qua)."""
    from data_sources import DB_CANONICAL_NGUON

    results = []
    all_affected: set[int] = set()
    for nguon in sorted(DB_CANONICAL_NGUON):
        try:
            r = merge_sheet_source_to_db(db, nguon, recompute_segments=False)
            results.append(r)
            all_affected.update(r.get("affected_tour_ids") or [])
        except Exception as e:
            logger.exception("Sheet sync failed for %s", nguon)
            results.append({"nguon": nguon, "error": str(e)})
    phan_khuc: dict = {}
    try:
        from pricing_segments import recompute_segments_for_sync, recompute_missing_phan_khuc

        if all_affected:
            phan_khuc = recompute_segments_for_sync(db, all_affected)
        else:
            phan_khuc = {"targeted_updated": 0}
        # LUÔN chạy recompute_missing_phan_khuc sau full sync — không chỉ khi
        # all_affected rỗng. Bắt các tour cũ bị mất phan_khuc do scrape lỗi /
        # mới insert / group baseline thay đổi sau khi recompute_segments_for_sync.
        # recompute_missing_phan_khuc tự skip VTR (theo design) nên không đụng VTR.
        phan_khuc["missing_filled"] = recompute_missing_phan_khuc(db)
    except Exception as e:
        logger.warning("recompute phan_khuc after full sheet sync failed: %s", e)
        phan_khuc = {"error": str(e)}
    _post_sync_cache(db)
    errors = [r for r in results if r.get("error")]
    return {
        "sources": results,
        "total_updated": sum(r.get("updated", 0) for r in results),
        "total_inserted": sum(r.get("inserted", 0) for r in results),
        "total_unchanged": sum(r.get("unchanged", 0) for r in results),
        "total_skipped": sum(r.get("skipped", 0) for r in results),
        "total_deleted": sum(r.get("deleted", 0) for r in results),
        "phan_khuc": phan_khuc,
        "ok": len(errors) == 0,
        "errors": errors,
    }
