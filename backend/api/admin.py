from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
    """Start background import — returns immediately (no HTTP timeout)."""
    from seed import start_import_background

    if not start_import_background():
        raise HTTPException(status_code=409, detail="Import đang chạy, vui lòng đợi...")
    return {"started": True, "message": "Import đang chạy nền. Trang sẽ tự cập nhật khi xong."}


@router.get("/data-status")
def data_status(_: User = Depends(get_current_user)):
    return _status_payload()
