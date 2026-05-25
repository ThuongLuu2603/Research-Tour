"""Workspace access control and default workspace provisioning."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import User, Workspace, WorkspaceMember

PERMISSION_RANK = {"view": 1, "copy": 2, "edit": 3}


def ensure_personal_workspace(db: Session, user: User) -> Workspace:
    ws = (
        db.query(Workspace)
        .filter(Workspace.owner_user_id == user.id, Workspace.is_personal.is_(True))
        .first()
    )
    if ws:
        return ws
    ws = Workspace(
        owner_user_id=user.id,
        name=f"Workspace — {user.display_name or user.username}",
        visibility="private",
        is_personal=True,
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def get_workspace_or_404(db: Session, workspace_id: int) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace không tồn tại")
    return ws


def get_member(db: Session, workspace_id: int, user_id: int) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def resolve_permission(db: Session, workspace: Workspace, user: User) -> str | None:
    if workspace.owner_user_id == user.id:
        return "edit"
    member = get_member(db, workspace.id, user.id)
    return member.permission if member else None


def require_permission(db: Session, workspace: Workspace, user: User, minimum: str) -> str:
    perm = resolve_permission(db, workspace, user)
    if not perm or PERMISSION_RANK.get(perm, 0) < PERMISSION_RANK[minimum]:
        raise HTTPException(status_code=403, detail="Không có quyền trên workspace này")
    return perm


def list_accessible_workspaces(db: Session, user: User) -> list[dict]:
    ensure_personal_workspace(db, user)
    owned = db.query(Workspace).filter(Workspace.owner_user_id == user.id).order_by(Workspace.is_personal.desc(), Workspace.id).all()
    shared_ids = [
        m.workspace_id
        for m in db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    ]
    shared = []
    if shared_ids:
        shared = db.query(Workspace).filter(Workspace.id.in_(shared_ids)).order_by(Workspace.name).all()

    seen: set[int] = set()
    rows: list[dict] = []
    for ws in owned + shared:
        if ws.id in seen:
            continue
        seen.add(ws.id)
        perm = resolve_permission(db, ws, user) or "view"
        rows.append({
            "id": ws.id,
            "name": ws.name,
            "owner_user_id": ws.owner_user_id,
            "is_personal": ws.is_personal,
            "visibility": ws.visibility,
            "permission": perm,
            "is_owner": ws.owner_user_id == user.id,
        })
    return rows
