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
    thi_truong: list[str] = Query([]),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    # Áp ĐỦ bộ lọc (thị trường + tuyến + điểm KH) qua compare context để đồng bộ với
    # mọi tab khác — trước đây load toàn bộ tour nên ma trận/KPI phủ sóng luôn hiện
    # toàn thị trường, lệch với thanh lọc chung. ctx.tours đã qua filter nguồn sẵn.
    from compare_cache import get_compare_context

    tours = get_compare_context(db, thi_truong, tuyen_tour, diem_kh, allow_stale=False).tours
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
    thi_truong: str = Query("", description="Lọc theo thị trường (giống bộ lọc trên)"),
    tuyen_tour: str = Query(""),
    diem_kh: str = Query(""),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    # Dùng CÙNG nguồn như matcher_detail (loại FindTourGo / VTR ảo trên catalog / FIT /
    # market 'Không xác định') — trước đây query thẳng toàn bảng nên gợi ý cả tour
    # không thuộc tập compare → click ra "tour không tồn tại". Phải khớp 2 dataset.
    tours = filter_tours_for_market_compare(_market_compare_tour_query(db).all())
    # Lọc danh sách tour VTR theo bộ lọc trên cùng (thị trường/tuyến/điểm KH).
    tt = thi_truong.strip(); rt = tuyen_tour.strip().lower(); dk = diem_kh.strip().lower()
    if tt:
        tours = [t for t in tours if (t.thi_truong or "").strip() == tt]
    if rt:
        tours = [t for t in tours if rt in (t.tuyen_tour or "").lower()]
    if dk:
        tours = [t for t in tours if dk in (t.diem_kh or "").lower()]
    return {"items": suggest_vtr_tours(tours)}


@router.get("/matcher/{tour_id}")
def matcher_detail(
    tour_id: str,  # CHUỖI: id CockroachDB ~1.18e18 > JS safe int → nhận str, convert int
    response: Response,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    response.headers["Cache-Control"] = f"private, max-age={_INTELLIGENCE_CACHE_SEC}"
    tours = filter_tours_for_market_compare(_market_compare_tour_query(db).all())
    try:
        tid = int(tour_id)
    except ValueError:
        return {"found": False, "message": "ID không hợp lệ"}
    return find_matches(tours, tid)


_REPORT_NS = "report_html_saved"


@router.get("/report/html", response_class=HTMLResponse)
def report_html(
    type: str = Query("daily"),
    refresh: bool = Query(False, description="Dựng lại báo cáo (xoá chỉnh sửa tay) — nút 'Làm mới'"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    # Phục vụ bản ĐÃ LƯU (gồm chỉnh sửa tay của admin) — chỉ dựng lại khi refresh=true
    # (nút Làm mới) hoặc khi snapshot ngày tự chạy. Mỗi lần vào KHÔNG dựng lại.
    from persistent_cache import load_text, save_text

    if not refresh:
        saved = load_text(_REPORT_NS, max_age_hours=None)
        if saved:
            return HTMLResponse(saved)
    html = build_report_html(db, type)
    try:
        save_text(_REPORT_NS, html, ttl_hours=24 * 30)
    except Exception:  # noqa: BLE001
        pass
    return HTMLResponse(html)


@router.put("/report/html")
def save_report_html(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Lưu ghi đè báo cáo đã chỉnh sửa tay (admin). Giữ tới khi Làm mới / snapshot ngày.

    Đồng thời TRÍCH ghi chú theo dòng (data-segkey) vào kho bền → giữ qua mỗi lần dựng
    lại (đổi %/giá hay đổi vị trí trong khung vẫn còn nhận định).
    """
    from persistent_cache import save_text
    import report_notes

    html = (body or {}).get("html") or ""
    if not html.strip():
        return {"saved": False, "reason": "empty"}
    save_text(_REPORT_NS, html, ttl_hours=24 * 30)
    try:
        notes = report_notes.extract_notes_from_html(html, base=report_notes.get_notes(db))
        report_notes.save_notes(db, notes)
    except Exception:  # noqa: BLE001
        pass
    return {"saved": True}


@router.get("/competitor-report/html", response_class=HTMLResponse)
def competitor_report_html(
    refresh: bool = Query(False, description="Dựng lại (xoá chỉnh sửa tay) — nút 'Làm mới'"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """So sánh đối thủ — phục vụ bản ĐÃ LƯU (load nhanh, KHÔNG build lại). Chỉ dựng
    lại khi refresh=true (nút Làm mới) hoặc khi chưa có bản lưu."""
    from competitor_report import get_saved_full, rebuild_and_save, clear_dep_map

    if not refresh:
        saved = get_saved_full(db)
        if saved:
            return HTMLResponse(saved)
    else:
        clear_dep_map(db)  # Làm mới = bỏ chỉnh sửa tay per-đầu
    return HTMLResponse(rebuild_and_save(db))


@router.get("/competitor-report/config")
def competitor_report_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Tuỳ chọn + cấu hình hiện tại (đầu KH + tuyến áp dụng cho báo cáo)."""
    from competitor_report import get_report_options

    return get_report_options(db)


@router.put("/competitor-report/config")
def save_competitor_report_config(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Lưu cấu hình báo cáo (admin): đầu KH + thị trường được chọn. Rỗng = tất cả."""
    from competitor_report import save_config

    departures = (body or {}).get("departures")
    markets = (body or {}).get("markets")
    if not isinstance(departures, list) or not isinstance(markets, list):
        return {"saved": False, "reason": "invalid"}
    save_config(db, departures, markets)
    try:
        from competitor_report import rebuild_and_save
        rebuild_and_save(db)  # dựng lại bản lưu theo cấu hình mới
    except Exception:  # noqa: BLE001
        pass
    return {"saved": True}


@router.get("/competitor-report/departures")
def competitor_report_departures(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Danh sách đầu khởi hành (để chọn khi sửa per-đầu)."""
    from competitor_report import build_competitor_report

    data = build_competitor_report(db)
    return {"departures": [
        {"diem_kh": d["diem_kh"], "total_tours": d["total_tours"], "markets": len(d["markets"])}
        for d in data["departures"]
    ]}


@router.get("/competitor-report/departure-html", response_class=HTMLResponse)
def competitor_report_departure_html(
    dep: str = Query(..., description="Tên đầu khởi hành"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """HTML 1 đầu khởi hành (standalone, nhỏ) để sửa trong TinyMCE."""
    from competitor_report import build_competitor_report, render_dep_doc, get_dep_map

    data = build_competitor_report(db)
    d = next((x for x in data["departures"] if x["diem_kh"] == dep), None)
    if not d:
        return HTMLResponse("<p>Không có đầu khởi hành này.</p>", status_code=404)
    saved = get_dep_map(db).get(dep)
    return HTMLResponse(render_dep_doc(d, data.get("peer_name", "Saigontourist"), saved))


@router.put("/competitor-report/departure-html")
def save_competitor_report_departure_html(
    body: dict,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Lưu bản sửa tay của 1 đầu khởi hành (admin) + dựng lại full HTML để load nhanh."""
    from competitor_report import save_dep_html, extract_body, rebuild_and_save

    dep = (body or {}).get("dep") or ""
    html = (body or {}).get("html") or ""
    if not dep or not html.strip():
        return {"saved": False, "reason": "empty"}
    save_dep_html(db, dep, extract_body(html))
    rebuild_and_save(db)  # cập nhật bản full đã lưu → lần xem sau nhanh
    return {"saved": True}


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
