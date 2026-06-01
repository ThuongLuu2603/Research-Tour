from __future__ import annotations

import io
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from api.auth import get_current_user
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/tours", tags=["tours"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TourOut(BaseModel):
    id: int
    cong_ty: str
    thi_truong: str
    tuyen_tour: str
    ten_tour: str
    lich_trinh: str
    diem_kh: str
    thoi_gian: str
    gia: float | None
    gia_raw: str
    lich_kh: str
    link_url: str
    ma_tour: str
    khach_san: str
    hang_khong: str
    so_ngay: float | None
    phan_khuc: str
    nguon: str
    analyst_note: str
    flagged: bool
    sheet_sync: dict | None = None

    model_config = {"from_attributes": True}


class TourPatch(BaseModel):
    thi_truong: str | None = None
    tuyen_tour: str | None = None
    cong_ty: str | None = None
    analyst_note: str | None = None
    flagged: bool | None = None
    sync_sheet: bool = True


class PaginatedTours(BaseModel):
    items: list[TourOut]
    total: int
    page: int
    page_size: int


class FilterOptions(BaseModel):
    thi_truong: list[str]
    tuyen_tour: list[str]
    cong_ty: list[str]
    diem_kh: list[str]
    nguon: list[str]
    phan_khuc: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=PaginatedTours)
def list_tours(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query(""),
    thi_truong: list[str] = Query([]),
    tuyen_tour: list[str] = Query([]),
    cong_ty: list[str] = Query([]),
    diem_kh: list[str] = Query([]),
    nguon: list[str] = Query([]),
    phan_khuc: list[str] = Query([]),
    flagged: bool | None = Query(None),
    gia_min: float | None = Query(None),
    gia_max: float | None = Query(None),
    sort_by: str = Query("id"),
    sort_dir: str = Query("desc"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Tour.ten_tour.ilike(like),
                Tour.cong_ty.ilike(like),
                Tour.ma_tour.ilike(like),
                Tour.lich_trinh.ilike(like),
            )
        )
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.in_(tuyen_tour))
    if cong_ty:
        q = q.filter(Tour.cong_ty.in_(cong_ty))
    if diem_kh:
        q = q.filter(Tour.diem_kh.in_(diem_kh))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    if phan_khuc:
        q = q.filter(Tour.phan_khuc.in_(phan_khuc))
    if flagged is not None:
        q = q.filter(Tour.flagged == flagged)
    if gia_min is not None:
        q = q.filter(Tour.gia >= gia_min)
    if gia_max is not None:
        q = q.filter(Tour.gia <= gia_max)

    total = q.count()

    sort_col = getattr(Tour, sort_by, Tour.id)
    if sort_dir == "desc":
        sort_col = sort_col.desc()
    q = q.order_by(sort_col)

    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedTours(items=items, total=total, page=page, page_size=page_size)


@router.get("/filter-options", response_model=FilterOptions)
def filter_options(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    def distinct(col):
        return [
            r[0]
            for r in db.query(col).filter(col != "").distinct().order_by(col).all()
        ]

    from data_sources import DB_CANONICAL_NGUON

    return FilterOptions(
        thi_truong=distinct(Tour.thi_truong),
        tuyen_tour=distinct(Tour.tuyen_tour),
        cong_ty=distinct(Tour.cong_ty),
        diem_kh=distinct(Tour.diem_kh),
        nguon=[n for n in distinct(Tour.nguon) if n in DB_CANONICAL_NGUON],
        phan_khuc=distinct(Tour.phan_khuc),
    )


@router.patch("/{tour_id}", response_model=TourOut)
def patch_tour(
    tour_id: int,
    patch: TourPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from classification import resolve_company_name
    from fastapi import HTTPException

    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Chỉ admin sửa dữ liệu chung. Dùng workspace trên tab Sản phẩm & Data.",
        )

    tour = db.query(Tour).filter(Tour.id == tour_id).first()
    if not tour:
        raise HTTPException(status_code=404, detail="Tour không tồn tại")

    data = patch.model_dump(exclude_none=True)
    sync_sheet = data.pop("sync_sheet", True)
    if "cong_ty" in data and data["cong_ty"]:
        data["cong_ty"] = resolve_company_name(data["cong_ty"])

    sheet_fields_changed = any(k in data for k in ("thi_truong", "tuyen_tour", "cong_ty"))
    for field, value in data.items():
        setattr(tour, field, value)
    db.commit()
    db.refresh(tour)

    sheet_sync = None
    if sync_sheet and sheet_fields_changed:
        from sheets_tour_sync import push_tour_to_sheet
        sheet_sync = push_tour_to_sheet(tour)

    return TourOut.model_validate(tour).model_copy(update={"sheet_sync": sheet_sync})


@router.get("/export/csv")
def export_csv(
    search: str = Query(""),
    thi_truong: list[str] = Query([]),
    tuyen_tour: list[str] = Query([]),
    cong_ty: list[str] = Query([]),
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = _apply_filters(
        db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon
    )
    tours = q.all()
    df = _tours_to_df(tours)
    output = io.BytesIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tours_export.csv"},
    )


@router.get("/export/excel")
def export_excel(
    search: str = Query(""),
    thi_truong: list[str] = Query([]),
    tuyen_tour: list[str] = Query([]),
    cong_ty: list[str] = Query([]),
    nguon: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = _apply_filters(
        db.query(Tour), search, thi_truong, tuyen_tour, cong_ty, nguon
    )
    tours = q.all()
    df = _tours_to_df(tours)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Tours")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tours_export.xlsx"},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_filters(q, search, thi_truong, tuyen_tour, cong_ty, nguon):
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Tour.ten_tour.ilike(like), Tour.cong_ty.ilike(like)))
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.in_(tuyen_tour))
    if cong_ty:
        q = q.filter(Tour.cong_ty.in_(cong_ty))
    if nguon:
        q = q.filter(Tour.nguon.in_(nguon))
    return q


def _tours_to_df(tours: list[Tour]) -> pd.DataFrame:
    COLS = [
        "cong_ty", "thi_truong", "tuyen_tour", "ten_tour",
        "lich_trinh", "diem_kh", "thoi_gian", "gia_raw", "lich_kh",
        "link_url", "khach_san", "hang_khong", "ma_tour", "nguon",
        "analyst_note", "flagged",
    ]
    return pd.DataFrame([{c: getattr(t, c, "") for c in COLS} for t in tours])
