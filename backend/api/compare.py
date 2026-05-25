from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user
from compare_engine import build_segment_stats, is_vietravel, segment_key
from config import settings
from database import get_db
from models import Tour, User

router = APIRouter(prefix="/api/compare", tags=["compare"])


class CompareSummary(BaseModel):
    company: str
    total_vietravel_tours: int
    segments_with_vietravel: int
    cheaper_count: int
    expensive_count: int
    similar_count: int
    avg_gap_pct: float | None


@router.get("/summary", response_model=CompareSummary)
def compare_summary(
    thi_truong: list[str] = Query([]),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    tours = q.all()
    segments = build_segment_stats(tours)
    cheaper = expensive = similar = 0
    gaps = []
    for s in segments:
        g = s.gap_pct
        if g is None:
            continue
        gaps.append(g)
        if g <= -5:
            cheaper += 1
        elif g >= 5:
            expensive += 1
        else:
            similar += 1
    vtr_count = sum(1 for t in tours if is_vietravel(t.cong_ty))
    return CompareSummary(
        company=settings.company_name,
        total_vietravel_tours=vtr_count,
        segments_with_vietravel=len(segments),
        cheaper_count=cheaper,
        expensive_count=expensive,
        similar_count=similar,
        avg_gap_pct=round(sum(gaps) / len(gaps), 1) if gaps else None,
    )


@router.get("/segments")
def compare_segments(
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    sort_by: str = Query("gap_pct"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)
    if thi_truong:
        q = q.filter(Tour.thi_truong.in_(thi_truong))
    if tuyen_tour:
        q = q.filter(Tour.tuyen_tour.ilike(f"%{tuyen_tour}%"))
    segments = build_segment_stats(q.all())
    rows = [s.to_dict() for s in segments]

    sort_key = {
        "gap_pct": lambda r: r.get("gap_pct") if r.get("gap_pct") is not None else 0,
        "vietravel_avg": lambda r: r.get("vietravel_avg_day") or 0,
        "market_avg": lambda r: r.get("market_avg_day") or 0,
        "tuyen_tour": lambda r: r.get("tuyen_tour") or "",
    }.get(sort_by, lambda r: r.get("gap_pct") or 0)
    reverse = sort_by in ("gap_pct", "vietravel_avg", "market_avg")
    rows.sort(key=sort_key, reverse=reverse)
    return {"methodology": _methodology_text(), "items": rows[:limit], "total": len(rows)}


@router.get("/segment-tours")
def segment_tours(
    key: str = Query(..., alias="segment_key"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    tours = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0).all()
    matched = []
    for t in tours:
        if segment_key(t) == key:
            days = t.so_ngay or 1
            matched.append({
                "id": t.id,
                "cong_ty": t.cong_ty,
                "ten_tour": t.ten_tour,
                "gia": t.gia,
                "gia_raw": t.gia_raw,
                "so_ngay": t.so_ngay,
                "gia_per_day": round(t.gia / days, 0) if days else None,
                "diem_kh": t.diem_kh,
                "link_url": t.link_url,
                "is_vietravel": is_vietravel(t.cong_ty),
            })
    matched.sort(key=lambda x: x["gia_per_day"] or 0)
    return {"segment_key": key, "tours": matched}


def _methodology_text() -> str:
    return (
        "Giá so sánh = Giá tour ÷ Số ngày. "
        "Chỉ so sánh tour cùng Tuyến tour + Điểm khởi hành + Thời lượng (ngày). "
        "VD: Bangkok-Pattaya 5N từ TP.HCM ≠ Bangkok-Pattaya 5N từ Hà Nội ≠ 4N từ TP.HCM."
    )
