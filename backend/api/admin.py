from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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
    """Import từ CSV gói (deploy) — chỉ khi DB thiếu tour; không kéo Sheet live."""
    from seed import start_import_background

    if not start_import_background():
        raise HTTPException(status_code=409, detail="Import đang chạy, vui lòng đợi...")
    return {"started": True, "message": "Import CSV gói đang chạy nền (nếu DB đã đủ ~8.410 Main thì không thay đổi)."}


@router.post("/sync-main-sheet-live")
def sync_main_sheet_live(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Kéo tab Main từ Google Sheet (live) → DB + phân loại lại bằng matcher."""
    from models import ScrapeJob
    from scrape_job_utils import reconcile_stale_scrape_jobs
    from seed import start_sheet_sync_background

    reconcile_stale_scrape_jobs(db)
    running = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.scraper_name == "sync_main", ScrapeJob.status == "running")
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail=f"Đang đồng bộ Main (job #{running.id})")

    job = ScrapeJob(
        scraper_name="sync_main",
        status="running",
        progress_pct=0,
        message="Đang đọc Google Sheet…",
        triggered_by=current_user.username,
        started_at=datetime.utcnow(),
        heartbeat_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if not start_sheet_sync_background(main_only=True, triggered_by=current_user.username, job_id=job.id):
        job.status = "failed"
        job.message = "Đồng bộ khác đang chạy"
        job.finished_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=409, detail="Đồng bộ đang chạy, vui lòng đợi...")
    return {"started": True, "job_id": str(job.id), "message": "Đang đồng bộ tab Main từ Google Sheet → DB…"}


@router.get("/data-status")
def data_status(_: User = Depends(get_current_user)):
    return _status_payload()


@router.post("/sync-tours-from-google-sheet")
def sync_tours_from_google_sheet(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Kéo thay đổi từ Google Sheet (live) → DB Research Grid (cả 3 tab)."""
    from sheets_tour_sync import merge_all_sheets_to_db
    from db_retry import run_with_retry

    try:
        return run_with_retry(lambda: merge_all_sheets_to_db(db), db=db, label="sync-all-sheets")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi đồng bộ Sheet → App: {e}") from e


@router.post("/sync-sheet-source")
def sync_sheet_source(
    nguon: str = Query(..., description="Vietravel | FindTourGo | Main"),
    recompute: bool = Query(
        True,
        description="Tính lại phân khúc ngay sau tab này. Khi đồng bộ nhiều tab, "
        "đặt false cho từng tab rồi gọi /recompute-phan-khuc 1 lần ở cuối (nhanh hơn).",
    ),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Đồng bộ tab Sheet → DB (Main | Vietravel). FindTourGo chỉ trên Sheet."""
    from data_sources import ALL_SHEET_TABS, is_db_canonical_source
    from sheets_tour_sync import merge_sheet_source_to_db
    from db_retry import run_with_retry

    if nguon not in ALL_SHEET_TABS:
        raise HTTPException(status_code=400, detail=f"nguon không hợp lệ: {nguon}")
    if not is_db_canonical_source(nguon):
        raise HTTPException(
            status_code=400,
            detail="FindTourGo chỉ lưu trên Google Sheet, không đồng bộ vào database",
        )
    try:
        return run_with_retry(
            lambda: merge_sheet_source_to_db(db, nguon, recompute_segments=recompute),
            db=db,
            label=f"sync-{nguon}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi đồng bộ tab {nguon}: {e}") from e


@router.post("/recompute-phan-khuc")
def recompute_phan_khuc(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tính lại Phân khúc: TB/ngày tour vs TB/ngày TT trên cùng Thị trường + Tuyến + Điểm KH."""
    from pricing_segments import recompute_all_phan_khuc
    from db_retry import run_with_retry

    try:
        result = run_with_retry(lambda: recompute_all_phan_khuc(db), db=db, label="recompute-phan-khuc")
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Sau khi phân khúc đổi → làm mới cache So sánh để số liệu phản ánh ngay (kết thúc luồng sync nhiều tab).
    try:
        from compare_cache import invalidate_compare_cache, prewarm_compare_cache
        from segment_mv import refresh_segment_mv

        invalidate_compare_cache()
        refresh_segment_mv()
        prewarm_compare_cache(db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("recompute-phan-khuc cache refresh skipped: %s", e)
    return result


@router.post("/sync-main-sheet")
def sync_main_sheet(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Chỉ đồng bộ tab Main (thị trường) — sau khi Google Apps Script cập nhật Sheet."""
    from sheets_tour_sync import merge_sheet_source_to_db
    try:
        return merge_sheet_source_to_db(db, "Main", mirror_delete=True, force_reclassify_all=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Lỗi đồng bộ Main: {e}") from e


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
    from workspace_service import ensure_personal_workspace
    ensure_personal_workspace(db, user)
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
