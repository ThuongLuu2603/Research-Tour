from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user, hash_password, require_admin
from database import get_db
from models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=6)
    display_name: str = ""
    role: str = "analyst"


class UpdateUserRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6)


class UserAdminOut(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    avatar_url: str
    is_active: bool
    last_login: str | None

    model_config = {"from_attributes": True}


def _status_payload():
    from seed import source_count, tour_count, SHEET_SOURCES, EXPECTED_MIN, get_import_status, bundled_files_info

    breakdown = {nguon: source_count(nguon) for nguon, _, _ in SHEET_SOURCES}
    breakdown["Main"] = source_count("Main")
    imp = get_import_status()
    return {
        "total": tour_count(),
        "breakdown": breakdown,
        "expected_min": EXPECTED_MIN,
        "complete": all(breakdown.get(n, 0) >= EXPECTED_MIN.get(n, 1) for n in EXPECTED_MIN),
        "import": imp,
        "bundled_files": bundled_files_info(),
    }


@router.post("/sync-data")
def sync_data(_: User = Depends(get_current_user)):
    from seed import start_import_background

    if not start_import_background():
        raise HTTPException(status_code=409, detail="Import đang chạy, vui lòng đợi...")
    return {"started": True, "message": "Import đang chạy nền."}


@router.get("/data-status")
def data_status(_: User = Depends(get_current_user)):
    return _status_payload()


@router.get("/users", response_model=list[UserAdminOut])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    out = []
    for u in users:
        out.append(UserAdminOut(
            id=u.id,
            username=u.username,
            display_name=u.display_name,
            role=u.role or "analyst",
            avatar_url=u.avatar_url or "",
            is_active=u.is_active,
            last_login=u.last_login.strftime("%d/%m/%Y %H:%M") if u.last_login else None,
        ))
    return out


@router.post("/users", response_model=UserAdminOut)
def create_user(req: CreateUserRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if req.role not in ("admin", "analyst"):
        raise HTTPException(status_code=400, detail="role phải là admin hoặc analyst")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="Username đã tồn tại")
    user = User(
        username=req.username.strip(),
        password_hash=hash_password(req.password),
        display_name=req.display_name.strip() or req.username,
        role=req.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserAdminOut(
        id=user.id, username=user.username, display_name=user.display_name,
        role=user.role, avatar_url=user.avatar_url or "", is_active=user.is_active, last_login=None,
    )


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: int,
    req: UpdateUserRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy user")
    if user.username == "admin" and req.is_active is False:
        raise HTTPException(status_code=400, detail="Không thể vô hiệu hóa tài khoản admin")
    if req.display_name is not None:
        user.display_name = req.display_name.strip()
    if req.role is not None:
        if req.role not in ("admin", "analyst"):
            raise HTTPException(status_code=400, detail="role không hợp lệ")
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.password:
        user.password_hash = hash_password(req.password)
    db.commit()
    db.refresh(user)
    return UserAdminOut(
        id=user.id, username=user.username, display_name=user.display_name,
        role=user.role, avatar_url=user.avatar_url or "", is_active=user.is_active,
        last_login=user.last_login.strftime("%d/%m/%Y %H:%M") if user.last_login else None,
    )
