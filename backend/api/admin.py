from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync-data")
def sync_data(_: User = Depends(get_current_user)):
    """Re-import sheet snapshots into DB (admin only)."""
    from seed import import_missing_sheets, source_count, tour_count, SHEET_SOURCES

    results = import_missing_sheets()
    return {
        "total": tour_count(),
        "breakdown": {nguon: source_count(nguon) for nguon, _, _ in SHEET_SOURCES},
        "imported": results,
    }


@router.get("/data-status")
def data_status(_: User = Depends(get_current_user)):
    from seed import source_count, tour_count, SHEET_SOURCES, EXPECTED_MIN

    breakdown = {nguon: source_count(nguon) for nguon, _, _ in SHEET_SOURCES}
    return {
        "total": tour_count(),
        "breakdown": breakdown,
        "expected_min": EXPECTED_MIN,
        "complete": all(breakdown.get(n, 0) >= EXPECTED_MIN.get(n, 1) for n, _, _ in SHEET_SOURCES),
    }
