"""Intelligence API — home brief, coverage, matcher, reports, alerts, quality."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, load_only

from api.auth import get_current_user, require_admin
from compare_engine import deduplicate_tours
from coverage_engine import build_coverage_for_api
from data_quality import compute_data_quality
from data_sources import MIN_VALID_PRICE
from database import get_db
from insight_engine import get_home_brief
from models import IntelAlert, SavedView, Tour, User
from product_matcher import find_matches, suggest_vtr_tours
from report_builder import build_report_html
from snapshot_service import capture_daily_snapshot
from tour_sources import apply_market_compare_source_filter, filter_tours_for_market_compare

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])

_INTELLIGENCE_CACHE_SEC = 300


def _market_compare_tour_query(db: Session):
    # KHÔNG dùng load_only: callers truy cập nhiều cột (festival_slug, province_code,
    # classification_rule_id, flagged...) → SQLAlchemy lazy-load per tour → N+1.
    # Postgres self-host: 1 query load full row ~5MB là vô tư, tránh 7000+ lookups.
    return apply_market_compare_source_filter(
        db.query(Tour)
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
    )


class SavedViewIn(BaseModel):
    name: str = Field(max_length=128)
    page: str = Field(max_length=64)
    filters: dict = Field(default_factory=dict)


class SavedViewOut(BaseModel):
    id: int
    name: str
    page: str
    filters: dict
    model_config = {"from_attributes": True}


class BulkTourPatch(BaseModel):
    tour_ids: list[int]
    thi_truong: str | None = None
    tuyen_tour: str | None = None
    flagged: bool | None = None


@router.get("/home")
def home_brief(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return get_home_brief(db)


@router.post("/snapshot/capture")
def capture_snapshot(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    from db_retry import run_with_retry

    tours = filter_tours_for_market_compare(_market_compare_tour_query(db).all())
    daily = run_with_retry(lambda: capture_daily_snapshot(db, tours), db=db, label="api-snapshot")
    return {"snapshot_date": daily.snapshot_date.isoformat(), "message": "Đã chụp snapshot & sinh insight"}


@router.get("/coverage")
def coverage(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    tours = filter_tours_for_market_compare(_market_compare_tour_query(db).all())
    # coverage_engine tự tính metrics khoảng trống (đoàn TT/tháng, giá/ngày, score) TỪ
    # tour CÓ lịch KH → không phụ thuộc snapshot RouteDailyMetrics (vốn hay trống/lệch key).
    result = build_coverage_for_api(tours)
    return result


@router.get("/coverage/segment")
def coverage_segment(
    thi_truong: str = Query(...),
    tuyen_tour: str = Query(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Chi tiết 1 ô ma trận phủ sóng (thị trường + tuyến): tóm tắt so sánh + danh sách
    tour VTR và đối thủ. Khóa khớp ĐÚNG coverage_engine: route = tuyen_tour or market."""
    from compare_engine import build_segment_stats, is_vietravel

    market = (thi_truong or "").strip() or "Khác"
    route = (tuyen_tour or "").strip() or market
    tours = deduplicate_tours(filter_tours_for_market_compare(_market_compare_tour_query(db).all()))
    sub = [
        t for t in tours
        if (((t.thi_truong or "").strip() or "Khác") == market
            and (((t.tuyen_tour or "").strip()) or (((t.thi_truong or "").strip()) or "Khác")) == route)
    ]

    def _brief(t) -> dict:
        return {
            "ten_tour": t.ten_tour or "",
            "cong_ty": t.cong_ty or "",
            "gia": float(t.gia) if t.gia else None,
            "gia_raw": getattr(t, "gia_raw", "") or "",
            "thoi_gian": t.thoi_gian or "",
            "diem_kh": t.diem_kh or "",
            "lich_kh": t.lich_kh or "",
            "link_url": t.link_url or "",
        }

    vtr = sorted([t for t in sub if is_vietravel(t.cong_ty)], key=lambda t: (t.gia or 0))
    mkt = sorted([t for t in sub if not is_vietravel(t.cong_ty)], key=lambda t: (t.gia or 0))
    segments = [s.to_dict() for s in build_segment_stats(sub, dedup=False)]
    return {
        "thi_truong": market,
        "tuyen_tour": route,
        "vtr_count": len(vtr),
        "market_count": len(mkt),
        "segments": segments,
        "vtr_tours": [_brief(t) for t in vtr],
        "market_tours": [_brief(t) for t in mkt],
    }


@router.get("/quality")
def quality(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return compute_data_quality(db)


@router.get("/matcher/suggest")
def matcher_suggest(
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    tours = (
        db.query(Tour)
        .options(load_only(
            Tour.id,
            Tour.ten_tour,
            Tour.ma_tour,
            Tour.link_url,
            Tour.gia_raw,
            Tour.lich_trinh,
            Tour.updated_at,
            Tour.created_at,
            Tour.cong_ty,
            Tour.thi_truong,
            Tour.tuyen_tour,
            Tour.diem_kh,
            Tour.thoi_gian,
            Tour.so_ngay,
            Tour.gia,
            Tour.lich_kh,
            Tour.nguon,
            Tour.sheet_source,
        ))
        .all()
    )
    return {"items": suggest_vtr_tours(tours)}


@router.get("/matcher/{tour_id}")
def matcher_detail(
    tour_id: int,
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    tours = filter_tours_for_market_compare(_market_compare_tour_query(db).all())
    return find_matches(tours, tour_id)


@router.get("/report/html", response_class=HTMLResponse)
def report_html(
    type: str = Query("daily"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return HTMLResponse(build_report_html(db, type))


@router.get("/alerts")
def list_alerts(
    unread_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    q = db.query(IntelAlert).order_by(IntelAlert.created_at.desc())
    if unread_only:
        q = q.filter(IntelAlert.is_read == False)  # noqa: E712
    rows = q.limit(50).all()
    return [
        {
            "id": a.id, "severity": a.severity, "category": a.category,
            "title": a.title, "message": a.message, "link_path": a.link_path,
            "is_read": a.is_read, "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


@router.post("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    a = db.query(IntelAlert).filter(IntelAlert.id == alert_id).first()
    if not a:
        raise HTTPException(404, "Alert không tồn tại")
    a.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/alerts/read-all")
def mark_all_read(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    db.query(IntelAlert).filter(IntelAlert.is_read == False).update({"is_read": True})  # noqa: E712
    db.commit()
    return {"ok": True}


@router.get("/views", response_model=list[SavedViewOut])
def list_views(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(SavedView).filter(SavedView.user_id == user.id).order_by(SavedView.created_at.desc()).all()
    return [
        SavedViewOut(id=r.id, name=r.name, page=r.page, filters=json.loads(r.filters_json or "{}"))
        for r in rows
    ]


@router.post("/views", response_model=SavedViewOut)
def save_view(body: SavedViewIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = SavedView(user_id=user.id, name=body.name, page=body.page, filters_json=json.dumps(body.filters, ensure_ascii=False))
    db.add(row)
    db.commit()
    db.refresh(row)
    return SavedViewOut(id=row.id, name=row.name, page=row.page, filters=body.filters)


@router.delete("/views/{view_id}")
def delete_view(view_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    row = db.query(SavedView).filter(SavedView.id == view_id, SavedView.user_id == user.id).first()
    if not row:
        raise HTTPException(404, "View không tồn tại")
    db.delete(row)
    db.commit()
    return {"deleted": view_id}


@router.post("/tours/bulk-patch")
def bulk_patch_tours(body: BulkTourPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Chỉ admin sửa dữ liệu chung. Dùng workspace trên Sản phẩm & Data.")
    if not body.tour_ids:
        raise HTTPException(400, "Chưa chọn tour")
    patch = body.model_dump(exclude={"tour_ids"}, exclude_none=True)
    if not patch:
        raise HTTPException(400, "Không có field cần cập nhật")
    updated = 0
    for t in db.query(Tour).filter(Tour.id.in_(body.tour_ids)).all():
        for k, v in patch.items():
            setattr(t, k, v)
        updated += 1
    db.commit()
    return {"updated": updated}
