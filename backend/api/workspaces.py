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
    cong_ty: str | None = None
    diem_kh: str | None = None
    analyst_note: str | None = None
    flagged: bool | None = None


class BulkOverridePatch(BaseModel):
    tour_ids: list[int]
    thi_truong: str | None = None
    tuyen_tour: str | None = None
    cong_ty: str | None = None
    diem_kh: str | None = None
    analyst_note: str | None = None
    flagged: bool | None = None


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


def _apply_tour_filters(q, search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc=None):
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

    q = _apply_tour_filters(db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc)
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
        "id", "ten_tour", "cong_ty", "thi_truong", "tuyen_tour", "thoi_gian",
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
    tour_id: int,
    patch: TourOverridePatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "edit")
    tour = db.query(Tour).filter(Tour.id == tour_id).first()
    if not tour:
        raise HTTPException(status_code=404, detail="Tour không tồn tại")

    data = build_override_patch(patch.model_dump(exclude_none=True))
    if not data:
        raise HTTPException(status_code=400, detail="Không có field cần cập nhật")

    if "cong_ty" in data and data["cong_ty"]:
        from classification import resolve_company_name
        data["cong_ty"] = resolve_company_name(data["cong_ty"])
    if "diem_kh" in data and data["diem_kh"]:
        from classification import resolve_departure_point
        data["diem_kh"] = resolve_departure_point(data["diem_kh"])

    _upsert_override(db, workspace_id, tour_id, user.id, data)
    db.commit()
    override = db.query(TourOverride).filter(
        TourOverride.workspace_id == workspace_id, TourOverride.tour_id == tour_id
    ).first()
    return merge_tour(tour, override).to_dict()


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
    for tour_id in body.tour_ids:
        if not db.query(Tour.id).filter(Tour.id == tour_id).first():
            continue
        _upsert_override(db, workspace_id, tour_id, user.id, patch)
        updated += 1
    db.commit()
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
    flagged: bool | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ws = get_workspace_or_404(db, workspace_id)
    require_permission(db, ws, user, "view")
    from data_sources import DB_CANONICAL_NGUON

    q = _apply_tour_filters(db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon, flagged, phan_khuc)
    q = q.filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
    tours = q.limit(5000).all()
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
