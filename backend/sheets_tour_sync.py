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
    }


def _find_db_tour(db, nguon: str, fields: dict, external_id: str) -> Tour | None:
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
    external_id: str = "",
    sheet_row: int | None = None,
) -> None:
    from classification import classify_route_fields, resolve_company_name, resolve_departure_point
    from seed import parse_ngay

    note = tour.analyst_note
    flagged = tour.flagged

    tour.cong_ty = resolve_company_name(fields["cong_ty"])[:256]
    tour.ten_tour = fields["ten_tour"][:512]
    tour.lich_trinh = fields["lich_trinh"]
    if nguon in ("Main", "Vietravel"):
        mk = (fields.get("thi_truong") or "").strip()
        rt = (fields.get("tuyen_tour") or "").strip()
        if not mk and not rt:
            mk, rt = classify_route_fields(tour.ten_tour, tour.lich_trinh)
        tour.thi_truong = mk[:128]
        tour.tuyen_tour = rt[:256]
        fields = {**fields, "thi_truong": tour.thi_truong, "tuyen_tour": tour.tuyen_tour}
    else:
        tour.thi_truong = fields["thi_truong"][:128]
        tour.tuyen_tour = fields["tuyen_tour"][:256]
    tour.diem_kh = resolve_departure_point(fields["diem_kh"])[:256]
    tour.thoi_gian = fields["thoi_gian"][:64]
    tour.gia_raw = fields["gia_raw"][:64]
    tour.gia = fields["gia"]
    tour.lich_kh = fields["lich_kh"]
    if fields["link_url"]:
        tour.link_url = fields["link_url"]
    if fields["ma_tour"]:
        tour.ma_tour = fields["ma_tour"][:64]
    tour.khach_san = _clean_field(fields.get("khach_san"))
    tour.hang_khong = _clean_field(fields.get("hang_khong"))
    tour.so_ngay = parse_ngay(fields["thoi_gian"])
    tour.phan_khuc = ""  # gán sau recompute_all_phan_khuc
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

    stale_ids = [
        tid
        for (tid,) in db.query(Tour.id)
        .filter(Tour.nguon == nguon, ~Tour.id.in_(synced_tour_ids))
        .all()
    ]
    if not stale_ids:
        return 0

    deleted = _delete_tour_ids(db, stale_ids)
    logger.info("Mirror prune %s: removed %s stale tours", nguon, deleted)
    return deleted


def purge_nguon_from_db(db, nguon: str) -> int:
    """Xóa toàn bộ tour một nguồn khỏi DB (vd. FindTourGo chỉ lưu Sheet)."""
    from models import Tour

    ids = [tid for (tid,) in db.query(Tour.id).filter(Tour.nguon == nguon).all()]
    if not ids:
        return 0
    deleted = _delete_tour_ids(db, ids)
    db.commit()
    logger.info("Purged %s tours with nguon=%s from DB", deleted, nguon)
    return deleted


def merge_dataframe_to_db(
    db,
    df,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
    progress: Callable[[int, str], None] | None = None,
    commit_batch: int = 80,
) -> dict:
    """Scraper → DB trước (Vietravel). Tour.id giữ nguyên khi match external_id."""
    from classification import _load_route_rules
    from data_sources import is_db_canonical_source, should_mirror_prune

    if not is_db_canonical_source(nguon):
        raise ValueError(f"Nguồn {nguon} không lưu DB — chỉ Sheet")
    if mirror_delete is None:
        mirror_delete = should_mirror_prune(nguon)

    from route_rule_matcher import RouteRuleMatcher

    matcher = RouteRuleMatcher(_load_route_rules()) if nguon in ("Vietravel", "Main") else None
    total = len(df)
    updated = inserted = skipped = unchanged = 0
    synced_tour_ids: set[int] = set()
    now = datetime.utcnow()
    for idx, (_, row) in enumerate(df.iterrows()):
        fields = _scrape_row_to_fields(row)
        if not fields:
            skipped += 1
            continue
        if not fields.get("gia"):
            skipped += 1
            continue
        if matcher:
            mk, rt, matched, _rid = matcher.resolve(
                fields["ten_tour"],
                fields["lich_trinh"],
            )
            if matched:
                fields["thi_truong"] = mk
                fields["tuyen_tour"] = rt

        external_id = compute_external_id(
            nguon,
            ma_tour=fields.get("ma_tour", ""),
            link_url=fields.get("link_url", ""),
            ten_tour=fields.get("ten_tour", ""),
        )
        tour = _find_db_tour(db, nguon, fields, external_id)
        is_new = tour is None
        if is_new:
            tour = _create_tour_from_fields(fields, nguon, now)
            tour.external_id = external_id[:128]
            db.add(tour)
            db.flush()
            synced_tour_ids.add(tour.id)
            inserted += 1
        else:
            synced_tour_ids.add(tour.id)
            new_hash = compute_content_hash(fields)
            if tour.content_hash == new_hash and tour.sheet_source == nguon:
                unchanged += 1
                continue
            updated += 1

        _apply_fields_to_tour(
            tour,
            fields,
            nguon,
            now,
            preserve_nguon=(not is_new and tour.nguon not in ("", nguon)),
            external_id=external_id,
        )

        if progress and (idx % 15 == 0 or idx + 1 == total):
            pct = 65 + int(17 * (idx + 1) / max(total, 1))
            progress(pct, f"Đang lưu DB {idx + 1}/{total} (+{inserted} mới, ~{updated} cập nhật)")
        if commit_batch > 0 and (idx + 1) % commit_batch == 0:
            db.commit()

    db.commit()
    _flush_search_after_commit(db, synced_tour_ids)

    deleted = 0
    if mirror_delete:
        deleted = _prune_stale_tours_for_source(db, nguon, synced_tour_ids)
        if deleted:
            db.commit()

    phan_khuc_stats: dict | None = None
    if recompute_segments and (inserted or updated or deleted):
        try:
            from pricing_segments import recompute_all_phan_khuc

            phan_khuc_stats = recompute_all_phan_khuc(db)
        except Exception as e:
            logger.warning("recompute phan_khuc after %s scrape failed: %s", nguon, e)
            phan_khuc_stats = {"error": str(e)}

    if inserted or updated or deleted:
        _post_sync_cache(db)

    out = {
        "nguon": nguon,
        "updated": updated,
        "inserted": inserted,
        "skipped": skipped,
        "unchanged": unchanged,
        "deleted": deleted,
        "synced": len(synced_tour_ids),
    }
    if phan_khuc_stats is not None:
        out["phan_khuc"] = phan_khuc_stats
    return out


def export_vietravel_tab_from_db(db) -> dict:
    """DB (nguon=Vietravel) → ghi đè tab Sheet Vietravel."""
    from models import Tour
    from scrapers.vietravel_scraper import db_tours_to_dataframe, write_to_google_sheet

    tours = db.query(Tour).filter(Tour.nguon == "Vietravel").order_by(Tour.id).all()
    df = db_tours_to_dataframe(tours)
    write_to_google_sheet(df)
    return {"ok": True, "rows": len(tours)}


def merge_sheet_source_to_db(
    db,
    nguon: str,
    *,
    mirror_delete: bool | None = None,
    recompute_segments: bool = True,
) -> dict:
    from data_sources import is_db_canonical_source, should_mirror_prune

    if not is_db_canonical_source(nguon):
        raise ValueError(
            f"Tab {nguon} không đồng bộ vào DB — FindTourGo chỉ lưu trên Google Sheet"
        )
    if mirror_delete is None:
        mirror_delete = should_mirror_prune(nguon)

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

    updated = inserted = skipped = unchanged = 0
    synced_tour_ids: set[int] = set()
    now = datetime.utcnow()
    for row_idx, row in enumerate(rows[1:], start=2):
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
        tour = _find_db_tour(db, nguon, fields, external_id)
        is_new = tour is None
        if is_new:
            if not fields.get("gia"):
                skipped += 1
                continue
            tour = _create_tour_from_fields(fields, nguon, now)
            db.add(tour)
            db.flush()
            synced_tour_ids.add(tour.id)
            inserted += 1
        else:
            synced_tour_ids.add(tour.id)
            new_hash = compute_content_hash(fields)
            if tour.content_hash == new_hash and tour.sheet_source == nguon:
                unchanged += 1
                continue
            updated += 1

        _apply_fields_to_tour(
            tour,
            fields,
            nguon,
            now,
            preserve_nguon=(not is_new and tour.nguon not in ("", nguon)),
            external_id=external_id,
            sheet_row=row_idx,
        )

    db.commit()
    _flush_search_after_commit(db, synced_tour_ids)

    deleted = 0
    if mirror_delete:
        deleted = _prune_stale_tours_for_source(db, nguon, synced_tour_ids)
        if deleted:
            db.commit()

    if inserted or updated or deleted:
        _post_sync_cache(db)

    phan_khuc_stats: dict | None = None
    if recompute_segments and (inserted or updated or deleted):
        try:
            from pricing_segments import recompute_all_phan_khuc

            phan_khuc_stats = recompute_all_phan_khuc(db)
        except Exception as e:
            logger.warning("recompute phan_khuc after %s sync failed: %s", nguon, e)
            phan_khuc_stats = {"error": str(e)}

    logger.info(
        "Sheet sync %s: inserted=%s updated=%s unchanged=%s skipped=%s deleted=%s synced=%s",
        nguon,
        inserted,
        updated,
        unchanged,
        skipped,
        deleted,
        len(synced_tour_ids),
    )
    out = {
        "nguon": nguon,
        "updated": updated,
        "inserted": inserted,
        "skipped": skipped,
        "unchanged": unchanged,
        "deleted": deleted,
        "synced": len(synced_tour_ids),
    }
    if phan_khuc_stats is not None:
        out["phan_khuc"] = phan_khuc_stats
    return out


def _flush_search_after_commit(db, tour_ids: set[int] | list[int]) -> None:
    """Sau commit — cập nhật tsvector GIN (PostgreSQL)."""
    from tour_search import sync_search_tsv_for_ids

    _ = db
    ids = [int(i) for i in tour_ids if i]
    if ids:
        sync_search_tsv_for_ids(ids)


def _post_sync_cache(db) -> None:
    try:
        from compare_cache import invalidate_compare_cache, prewarm_compare_cache
        from segment_mv import refresh_segment_mv

        invalidate_compare_cache()
        prewarm_compare_cache(db)
        refresh_segment_mv()
    except Exception as e:
        logger.warning("post-sync cache refresh failed: %s", e)


def merge_all_sheets_to_db(db) -> dict:
    """Sheet → DB: chỉ Main + Vietravel (FindTourGo bỏ qua)."""
    from data_sources import DB_CANONICAL_NGUON

    results = []
    for nguon in sorted(DB_CANONICAL_NGUON):
        try:
            results.append(
                merge_sheet_source_to_db(db, nguon, recompute_segments=False)
            )
        except Exception as e:
            logger.exception("Sheet sync failed for %s", nguon)
            results.append({"nguon": nguon, "error": str(e)})
    phan_khuc: dict = {}
    try:
        from pricing_segments import recompute_all_phan_khuc

        phan_khuc = recompute_all_phan_khuc(db)
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
