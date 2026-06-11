from __future__ import annotations

import io
import json
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from api.auth import get_current_user
from database import get_db
from models import Tour, TourOverride, User, Workspace, WorkspaceMember
from tour_effective import TOUR_EXPORT_FIELDS, build_override_patch, merge_tour
from workspace_service import (
    ensure_personal_workspace,
    get_workspace_or_404,
    list_accessible_workspaces,
    require_permission,
    resolve_permission,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: int
    name: str
    owner_user_id: int
    is_personal: bool
    visibility: str
    permission: str
    is_owner: bool


class TourOverridePatch(BaseModel):
    thi_truong: str | None = None
    tuyen_tour: str | None = None
    thoi_gian: str | None = None
    cong_ty: str | None = None
    diem_kh: str | None = None
    analyst_note: str | None = None
    flagged: bool | None = None


class BulkOverridePatch(BaseModel):
    # Accept string OR int; convert to int trong handler.
    # Lý do: CockroachDB unique_rowid() > 2^53, JS round → frontend gửi string.
    tour_ids: list[str | int]
    thi_truong: str | None = None
    tuyen_tour: str | None = None
    thoi_gian: str | None = None
    cong_ty: str | None = None
    diem_kh: str | None = None
    analyst_note: str | None = None
    flagged: bool | None = None


# Admin sửa các trường này → ghi THẲNG DB (chung) + khóa quy tắc; còn lại → override workspace (riêng user).
_ADMIN_DB_FIELDS = ("thi_truong", "tuyen_tour", "thoi_gian", "diem_kh")


def _admin_write_classification(db, tour, data: dict, user) -> tuple[dict, bool]:
    """Nếu user là admin: rút Thị trường/Tuyến/Thời gian khỏi ``data``, ghi thẳng DB + khóa.
    Trả về (data còn lại để lưu override, đã_ghi_DB?). Non-admin: trả nguyên data, False.

    STICKY guard: empty string "" → skip (KHÔNG wipe), giống None.
    Frontend payload thường chỉ gồm field đã edit, nhưng nếu form state stale gửi
    chuỗi rỗng → phải bảo vệ tránh wipe dữ liệu admin đã nhập."""
    if (getattr(user, "role", "") or "") != "admin":
        return data, False
    remaining = dict(data)
    wrote = False
    if "thi_truong" in remaining:
        v = remaining.pop("thi_truong") or ""
        if v.strip():
            tour.thi_truong = v[:128]
            wrote = True
        # else: empty → skip (giữ giá trị cũ)
    if "tuyen_tour" in remaining:
        v = remaining.pop("tuyen_tour") or ""
        if v.strip():
            tour.tuyen_tour = v[:256]
            wrote = True
    if "thoi_gian" in remaining:
        v = (remaining.pop("thoi_gian") or "").strip()
        if v:
            # Chuẩn hóa về NĐ (7N6Đ) khi khớp alias; giữ raw nếu không khớp.
            from classification import normalize_duration_text
            from seed import parse_ngay
            norm_tg, norm_sn = normalize_duration_text(v, None)
            tour.thoi_gian = (norm_tg or v)[:64]
            tour.so_ngay = norm_sn if norm_sn is not None else parse_ngay(v)
            wrote = True
    # Điểm khởi hành: admin sửa → ghi THẲNG DB + khóa (giống TT/Tuyến/Thời gian).
    # Option đến từ Quy tắc phân loại (canonical) nên ghi trực tiếp.
    if "diem_kh" in remaining:
        v = (remaining.pop("diem_kh") or "").strip()
        if v:
            tour.diem_kh = v[:256]
            wrote = True
        # else: empty → skip (sticky, không wipe)
    # cong_ty: KHÔNG phải admin-DB field → vẫn qua override. Guard không wipe khi rỗng.
    if "cong_ty" in remaining:
        v = (remaining.get("cong_ty") or "").strip()
        if not v:
            remaining.pop("cong_ty", None)
    if wrote:
        from datetime import datetime
        tour.manual_locked = True       # quy tắc + sheet không ghi đè khi tour update (tên không đổi)
        if (tour.nguon or "") == "Vietravel":
            # VTR: phân khúc = Dòng tour, recompute SKIP Vietravel → nếu blank ở
            # đây thì rỗng đến lần scrape sau. Giữ nguyên (hoặc đồng bộ lại từ
            # dong_tour nếu có) thay vì wipe.
            if (tour.dong_tour or "").strip():
                tour.phan_khuc = (tour.dong_tour or "").strip()[:64]
        else:
            tour.phan_khuc = ""         # buộc tính lại phân khúc giá (recompute ngay sau PATCH)
        tour.updated_at = datetime.utcnow()
    return remaining, wrote


def _recompute_phan_khuc_background(tour_ids: list[int]) -> None:
    """Defer phân khúc recompute to background thread — KHÔNG block PATCH response.
    Tự mở Session riêng (Session caller đã close khi request return)."""
    if not tour_ids:
        return
    import logging
    import threading

    log = logging.getLogger(__name__)

    def _run() -> None:
        from database import SessionLocal
        bg = SessionLocal()
        try:
            from pricing_segments import recompute_phan_khuc_for_tour_ids
            recompute_phan_khuc_for_tour_ids(bg, list(tour_ids))
            bg.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("Background phân khúc recompute failed for %d tours: %s", len(tour_ids), e)
            try:
                bg.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            bg.close()

    t = threading.Thread(target=_run, daemon=True, name="phan-khuc-recompute")
    t.start()


class ShareWorkspaceRequest(BaseModel):
    username: str
    permission: str = "view"


class CopyWorkspaceRequest(BaseModel):
    source_workspace_id: int


class PaginatedEffectiveTours(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    workspace_id: int


def _override_map(db: Session, workspace_id: int, tour_ids: list[int]) -> dict[int, TourOverride]:
    if not tour_ids:
        return {}
    rows = (
        db.query(TourOverride)
        .filter(TourOverride.workspace_id == workspace_id, TourOverride.tour_id.in_(tour_ids))
        .all()
    )
    return {r.tour_id: r for r in rows}


def _upsert_override(db: Session, workspace_id: int, tour_id: int, user_id: int, patch: dict[str, Any]) -> TourOverride:
    row = (
        db.query(TourOverride)
        .filter(TourOverride.workspace_id == workspace_id, TourOverride.tour_id == tour_id)
        .first()
    )
    merged = {}
    if row:
        try:
            merged = json.loads(row.overrides_json or "{}")
        except Exception:
            merged = {}
    merged.update(patch)
    if row:
        row.overrides_json = json.dumps(merged, ensure_ascii=False)
        row.updated_by = user_id
    else:
        row = TourOverride(
            workspace_id=workspace_id,
            tour_id=tour_id,
            updated_by=user_id,
            overrides_json=json.dumps(merged, ensure_ascii=False),
        )
        db.add(row)
    return row


def _apply_tour_filters(q, search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc=None, diem_kh=None):
    if search:
        from tour_search import apply_search_filter

        q = apply_search_filter(q, search)
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.in_(tuyen_tour))
    if cong_ty:
        q = q.filter(Tour.cong_ty.in_(cong_ty))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    if phan_khuc:
        q = q.filter(Tour.phan_khuc.in_(phan_khuc))
    if diem_kh:
        q = q.filter(Tour.diem_kh.in_(diem_kh))
    if flagged is not None:
        q = q.filter(Tour.flagged == flagged)
    return q


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return list_accessible_workspaces(db, user)


@router.get("/{workspace_id}/tours", response_model=PaginatedEffectiveTours)
def list_workspace_tours(
    workspace_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    thi_truong: list[str] = Query([]),
    tuyen_tour: list[str] = Query([]),
    cong_ty: list[str] = Query([]),
    nguon: list[str] = Query([]),
    phan_khuc: list[str] = Query([]),
    diem_kh: list[str] = Query([]),
    flagged: bool | None = Query(None),
    only_overridden: bool = Query(False),
    sort_by: str = Query("id"),
    sort_dir: str = Query("desc"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "view")

    from data_sources import DB_CANONICAL_NGUON

    q = _apply_tour_filters(db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc, diem_kh)
    q = q.filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))

    if only_overridden:
        override_tour_ids = [
            r[0]
            for r in db.query(TourOverride.tour_id).filter(TourOverride.workspace_id == workspace_id).all()
        ]
        if not override_tour_ids:
            return PaginatedEffectiveTours(items=[], total=0, page=page, page_size=page_size, workspace_id=workspace_id)
        q = q.filter(Tour.id.in_(override_tour_ids))

    total = q.count()
    _sortable = frozenset({
        "id", "ten_tour", "cong_ty", "thi_truong", "tuyen_tour", "diem_kh", "thoi_gian",
        "gia", "phan_khuc", "nguon", "analyst_note", "updated_at", "created_at",
    })
    sort_field = sort_by if sort_by in _sortable else "id"
    sort_col = getattr(Tour, sort_field, Tour.id)
    if sort_dir == "asc":
        order = sort_col.asc()
    else:
        order = sort_col.desc()
    tours = q.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    overrides = _override_map(db, workspace_id, [t.id for t in tours])
    items = [merge_tour(t, overrides.get(t.id)).to_dict() for t in tours]
    perm = resolve_permission(db, ws, user) or "view"
    return PaginatedEffectiveTours(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        workspace_id=workspace_id,
    )


@router.patch("/{workspace_id}/tours/{tour_id}")
def patch_workspace_tour(
    workspace_id: int,
    tour_id: str,  # CockroachDB unique_rowid() > 2^53 → nhận string từ URL
    patch: TourOverridePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "edit")
    try:
        tour_id_int = int(tour_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"tour_id không hợp lệ: {tour_id}") from e
    tour = db.query(Tour).filter(Tour.id == tour_id_int).first()
    if not tour:
        raise HTTPException(status_code=404, detail=f"Tour {tour_id} không tồn tại")
    tour_id = tour_id_int  # gán lại cho code dưới dùng int

    data = build_override_patch(patch.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(status_code=400, detail="Không có field cần cập nhật")

    if "cong_ty" in data and data["cong_ty"]:
        from classification import resolve_company_name
        data["cong_ty"] = resolve_company_name(data["cong_ty"])
    if "diem_kh" in data and data["diem_kh"]:
        from classification import resolve_departure_point
        data["diem_kh"] = resolve_departure_point(data["diem_kh"])

    # Admin: market/route/duration ghi thẳng DB + khóa; phần còn lại → override workspace.
    data, wrote_db = _admin_write_classification(db, tour, data, user)
    if data:
        _upsert_override(db, workspace_id, tour_id, user.id, data)
    db.commit()
    # Recompute phân khúc ĐỒNG BỘ cho 1 tour (cache route_avg 60s → sub-second).
    # Trước đây dùng background thread + frontend setTimeout 2s — race condition trên
    # VPS chậm (build route_avg ~3-5s) → UI đọc giá trị "" → hiển thị "—".
    if wrote_db:
        try:
            from pricing_segments import recompute_phan_khuc_for_single_tour_sync
            recompute_phan_khuc_for_single_tour_sync(db, tour)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "Sync phân khúc recompute failed cho tour %d: %s", tour_id, e
            )
    override = db.query(TourOverride).filter(
        TourOverride.workspace_id == workspace_id, TourOverride.tour_id == tour_id
    ).first()
    result = merge_tour(tour, override).to_dict()
    return result


@router.post("/{workspace_id}/tours/bulk-patch")
def bulk_patch_workspace_tours(
    workspace_id: int,
    body: BulkOverridePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "edit")
    if not body.tour_ids:
        raise HTTPException(status_code=400, detail="Chưa chọn tour")
    patch = build_override_patch(body.model_dump(exclude={"tour_ids"}, exclude_none=True))
    if not patch:
        raise HTTPException(status_code=400, detail="Không có field cần cập nhật")
    if "cong_ty" in patch and patch["cong_ty"]:
        from classification import resolve_company_name
        patch["cong_ty"] = resolve_company_name(patch["cong_ty"])
    updated = 0
    wrote_ids: list[int] = []
    for raw_tid in body.tour_ids:
        try:
            tour_id = int(raw_tid)
        except (ValueError, TypeError):
            continue
        tour = db.query(Tour).filter(Tour.id == tour_id).first()
        if not tour:
            continue
        # Admin: market/route/duration ghi thẳng DB + khóa; còn lại → override.
        remaining, wrote_db = _admin_write_classification(db, tour, dict(patch), user)
        if remaining:
            _upsert_override(db, workspace_id, tour_id, user.id, remaining)
        if wrote_db:
            wrote_ids.append(tour_id)
        updated += 1
    db.commit()
    # Bulk: nhiều tour → background OK. Cache route_avg invalidated trước recompute để
    # đảm bảo các edit khác dùng dữ liệu fresh sau bulk.
    if wrote_ids:
        try:
            from pricing_segments import invalidate_route_avg_cache
            invalidate_route_avg_cache()
        except Exception:  # noqa: BLE001
            pass
        _recompute_phan_khuc_background(wrote_ids)
    return {"updated": updated, "workspace_id": workspace_id}


@router.post("/{workspace_id}/share")
def share_workspace(
    workspace_id: int,
    body: ShareWorkspaceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if body.permission not in ("view", "edit", "copy"):
        raise HTTPException(status_code=400, detail="permission phải là view, edit hoặc copy")
    ws = get_workspace_or_404(db, workspace_id)
    if ws.owner_user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ chủ workspace mới chia sẻ được")
    target = db.query(User).filter(User.username == body.username.strip()).first()
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy user")
    if target.id == ws.owner_user_id:
        raise HTTPException(status_code=400, detail="Không thể chia sẻ với chính chủ workspace")
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == target.id,
    ).first()
    if member:
        member.permission = body.permission
    else:
        db.add(WorkspaceMember(workspace_id=workspace_id, user_id=target.id, permission=body.permission))
    if ws.is_personal:
        ws.visibility = "shared"
    db.commit()
    return {"ok": True, "username": target.username, "permission": body.permission}


@router.delete("/{workspace_id}/share/{member_user_id}")
def revoke_workspace_share(
    workspace_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    if ws.owner_user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ chủ workspace mới thu hồi quyền")
    member = db.query(WorkspaceMember).filter(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == member_user_id,
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="Thành viên không tồn tại")
    db.delete(member)
    db.commit()
    return {"deleted": member_user_id}


@router.get("/{workspace_id}/members")
def list_workspace_members(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "view")
    owner = db.query(User).filter(User.id == ws.owner_user_id).first()
    members = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).all()
    rows = [{
        "user_id": owner.id if owner else ws.owner_user_id,
        "username": owner.username if owner else "",
        "display_name": owner.display_name if owner else "",
        "permission": "edit",
        "is_owner": True,
    }]
    for m in members:
        u = db.query(User).filter(User.id == m.user_id).first()
        rows.append({
            "user_id": m.user_id,
            "username": u.username if u else "",
            "display_name": u.display_name if u else "",
            "permission": m.permission,
            "is_owner": False,
        })
    return {"workspace_id": workspace_id, "members": rows}


@router.post("/{workspace_id}/copy-from")
def copy_overrides_from_workspace(
    workspace_id: int,
    body: CopyWorkspaceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target = get_workspace_or_404(db, workspace_id)
    require_permission(db, target, user, "edit")
    source = get_workspace_or_404(db, body.source_workspace_id)
    require_permission(db, source, user, "copy")

    personal = ensure_personal_workspace(db, user)
    dest_id = workspace_id if resolve_permission(db, target, user) == "edit" else personal.id

    src_rows = db.query(TourOverride).filter(TourOverride.workspace_id == source.id).all()
    copied = 0
    for row in src_rows:
        try:
            patch = json.loads(row.overrides_json or "{}")
        except Exception:
            patch = {}
        if not patch:
            continue
        _upsert_override(db, dest_id, row.tour_id, user.id, patch)
        copied += 1
    db.commit()
    return {"copied": copied, "destination_workspace_id": dest_id}


@router.get("/{workspace_id}/export/csv")
def export_workspace_csv(
    workspace_id: int,
    search: str = Query(""),
    thi_truong: list[str] = Query([]),
    tuyen_tour: list[str] = Query([]),
    cong_ty: list[str] = Query([]),
    nguon: list[str] = Query([]),
    phan_khuc: list[str] = Query([]),
    diem_kh: list[str] = Query([]),
    flagged: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "view")
    from data_sources import DB_CANONICAL_NGUON

    q = _apply_tour_filters(db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc, diem_kh)
    q = q.filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
    # Trước đây cap 5000 — user phản ánh DB có ~7000 tour Main + Vietravel nhưng tải về
    # chỉ thấy 5000. Tăng lên 50000 (ceiling an toàn để không OOM); CSV ~7000 tour
    # khoảng vài MB, vẫn thoải mái streaming.
    tours = q.limit(50000).all()
    overrides = _override_map(db, workspace_id, [t.id for t in tours])
    rows = [merge_tour(t, overrides.get(t.id)).to_dict() for t in tours]
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=workspace_{workspace_id}_tours.csv"},
    )
