from __future__ import annotations

import asyncio
import re
import sys
import threading
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user, user_from_access_token
from database import get_db, SessionLocal
from models import ScrapeJob, Tour, User

router = APIRouter(prefix="/api/scraper", tags=["scraper"])

# Active job progress messages: job_id → list[str]
_progress_queues: dict[int, asyncio.Queue] = {}


# ── Schemas ───────────────────────────────────────────────────────────────────

class TriggerRequest(BaseModel):
    scraper: str  # "vietravel" | "findtourgo"


class JobOut(BaseModel):
    id: int
    scraper_name: str
    status: str
    progress_pct: int
    message: str
    tours_added: int
    tours_updated: int
    tours_total: int
    triggered_by: str
    started_at: datetime
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class ScheduleConfig(BaseModel):
    hour: int
    minute: int


# ── Trigger ───────────────────────────────────────────────────────────────────

@router.post("/trigger", response_model=JobOut)
def trigger_scrape(
    req: TriggerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.scraper not in ("vietravel", "findtourgo"):
        raise HTTPException(status_code=400, detail="scraper phải là 'vietravel' hoặc 'findtourgo'")

    from scrape_job_utils import reconcile_stale_scrape_jobs

    reconcile_stale_scrape_jobs(db)

    running = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.scraper_name == req.scraper, ScrapeJob.status == "running")
        .first()
    )
    if running:
        raise HTTPException(status_code=409, detail=f"Đang có job {req.scraper} chạy (id={running.id})")

    job = ScrapeJob(
        scraper_name=req.scraper,
        status="pending",
        triggered_by=current_user.username,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    thread = threading.Thread(target=_run_job, args=(job.id, req.scraper), daemon=True)
    thread.start()

    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    limit: int = 30,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    from scrape_job_utils import reconcile_stale_scrape_jobs

    reconcile_stale_scrape_jobs(db)
    return (
        db.query(ScrapeJob)
        .order_by(ScrapeJob.started_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/jobs/reconcile-stale")
def reconcile_stale_jobs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Dọn mọi job pending/running treo — gọi khi Job History kẹt «running»."""
    from scrape_job_utils import reconcile_stale_scrape_jobs

    fixed = reconcile_stale_scrape_jobs(db)
    return {"message": f"Đã dọn {len(fixed)} job treo", "fixed_ids": fixed}


@router.post("/jobs/{job_id}/cancel")
def cancel_stale_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Đánh dấu job pending/running là failed — mở khóa «Chạy ngay»."""
    job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Job đã {job.status}, không hủy được")
    job.status = "failed"
    job.finished_at = datetime.utcnow()
    job.message = ((job.message or "").strip() + " | Đã hủy thủ công trên UI")[:512]
    db.commit()
    return {"message": f"Đã hủy job #{job_id}", "job_id": job_id}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    return job


@router.get("/jobs/{job_id}/stream")
async def stream_job(
    job_id: int,
    token: str | None = Query(None, description="JWT (EventSource không gửi được header Authorization)"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    """SSE stream: client receives progress events until job completes."""
    raw = (token or "").strip()
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Thiếu token — đăng nhập lại")
    user_from_access_token(raw, db)

    async def event_gen() -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        _progress_queues[job_id] = queue
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
                    continue
                yield f"data: {msg}\n\n"
                if msg.startswith('{"done":true') or msg.startswith('{"error":'):
                    break
        finally:
            _progress_queues.pop(job_id, None)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/registry")
def scraper_registry(_: User = Depends(get_current_user)):
    from scrapers.registry import list_scrapers
    return {"items": list_scrapers()}


@router.get("/schedule")
def get_schedule(_: User = Depends(get_current_user)):
    from scheduler import get_schedule_config
    return get_schedule_config()


@router.post("/schedule")
def update_schedule(
    cfg: ScheduleConfig,
    _: User = Depends(get_current_user),
):
    from scheduler import update_schedule_config
    update_schedule_config(cfg.hour, cfg.minute)
    return {"message": f"Lịch cập nhật: {cfg.hour:02d}:{cfg.minute:02d} hàng ngày"}


# ── Background worker ─────────────────────────────────────────────────────────

_SCRAPE_TIMEOUT_SEC = {
    "vietravel": 3600,
    "findtourgo": 2700,
}


def _persist_job_progress(job_id: int, pct: int, msg: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job and job.status in ("pending", "running"):
            job.progress_pct = max(0, min(100, pct))
            job.message = (msg or "")[:512]
            job.heartbeat_at = datetime.utcnow()
            if job.status == "pending":
                job.status = "running"
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _emit(job_id: int, pct: int, msg: str):
    import json

    _persist_job_progress(job_id, pct, msg)
    payload = json.dumps({"pct": pct, "msg": msg, "done": False}, ensure_ascii=False)
    q = _progress_queues.get(job_id)
    if q:
        try:
            asyncio.run_coroutine_threadsafe(q.put(payload), _get_event_loop())
        except Exception:
            pass


def _emit_done(job_id: int, added: int, updated: int, deleted: int = 0):
    import json
    msg = f"Hoàn thành: +{added} mới, ~{updated} cập nhật"
    if deleted:
        msg += f", −{deleted} đã xóa (không còn trên Sheet)"
    payload = json.dumps(
        {"pct": 100, "msg": msg, "done": True, "added": added, "updated": updated, "deleted": deleted},
        ensure_ascii=False,
    )
    q = _progress_queues.get(job_id)
    if q:
        asyncio.run_coroutine_threadsafe(q.put(payload), _get_event_loop())


def _emit_error(job_id: int, msg: str):
    import json
    payload = json.dumps({"pct": 0, "msg": msg, "error": True, "done": True})
    q = _progress_queues.get(job_id)
    if q:
        asyncio.run_coroutine_threadsafe(q.put(payload), _get_event_loop())


_loop: asyncio.AbstractEventLoop | None = None


def _get_event_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        import asyncio as _asyncio
        _loop = _asyncio.get_event_loop()
    return _loop


def set_event_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def _run_job(job_id: int, scraper_name: str):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    from runtime_state import wait_db_ready

    if not wait_db_ready(timeout=300):
        db = SessionLocal()
        try:
            job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.message = "Database chưa sẵn sàng sau 5 phút — thử lại sau khi deploy xong"
                job.finished_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
        _emit_error(job_id, "Database chưa sẵn sàng")
        return

    db = SessionLocal()
    try:
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.heartbeat_at = datetime.utcnow()
        db.commit()

        _emit(job_id, 5, f"Bắt đầu quét {scraper_name}...")

        timeout = _SCRAPE_TIMEOUT_SEC.get(scraper_name, 3600)

        def _work():
            if scraper_name == "vietravel":
                return _run_vietravel(db, job_id, job)
            return _run_findtourgo(db, job_id, job)

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_work)
            try:
                added, updated, deleted = fut.result(timeout=timeout)
            except FuturesTimeout:
                raise TimeoutError(
                    f"Scraper {scraper_name} quá {timeout // 60} phút — hủy để tránh job treo"
                ) from None

        job.status = "success"
        job.progress_pct = 100
        job.tours_added = added
        job.tours_updated = updated
        job.finished_at = datetime.utcnow()
        if deleted:
            job.message = f"−{deleted} tour đã xóa khỏi DB (không còn trên Sheet)"
        db.commit()
        _emit_done(job_id, added, updated, deleted)
        try:
            from snapshot_service import capture_daily_snapshot
            capture_daily_snapshot(db)
        except Exception:
            pass

    except Exception as exc:
        db.rollback()
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.message = str(exc)[:512]
            job.finished_at = datetime.utcnow()
            db.commit()
        _emit_error(job_id, f"Lỗi: {exc}")
    finally:
        db.close()


def _run_vietravel(db: Session, job_id: int, job: ScrapeJob):
    sys.path.insert(0, "scrapers")
    from scrapers.vietravel_scraper import scrape_all_vietravel_tours
    from sheets_tour_sync import export_vietravel_tab_from_db, merge_dataframe_to_db

    def _progress(pct: int, msg: str) -> None:
        _emit(job_id, pct, msg)

    _emit(job_id, 10, "Bắt đầu quét travel.com.vn...")
    df = scrape_all_vietravel_tours(progress=_progress, classify=False)
    if df.empty:
        raise RuntimeError("Không quét được tour từ travel.com.vn — site có thể đổi cấu trúc hoặc chặn bot")
    _emit(job_id, 52, f"Đã quét {len(df)} tour — đang lưu DB…")

    job.tours_total = len(df)
    db.commit()

    result = merge_dataframe_to_db(
        db,
        df,
        "Vietravel",
        mirror_delete=True,
        recompute_segments=False,
        progress=_progress,
    )

    _emit(job_id, 84, "Đã lưu DB — đang ghi Google Sheet…")
    try:
        export_vietravel_tab_from_db(db)
    except Exception as e:
        _emit(job_id, 88, f"DB đã lưu; ghi Sheet lỗi: {e}")

    return (
        result.get("inserted", 0),
        result.get("updated", 0),
        result.get("deleted", 0),
    )


def _run_findtourgo(db: Session, job_id: int, job: ScrapeJob):
    sys.path.insert(0, "scrapers")
    from scrapers.findtourgo_scraper import scrape_all_findtourgo_tours, write_to_google_sheet

    def _progress(pct: int, msg: str) -> None:
        _emit(job_id, pct, msg)

    _emit(job_id, 8, "Bắt đầu quét FindTourGo API…")
    df = scrape_all_findtourgo_tours(progress=_progress, classify=False)
    if df.empty:
        raise RuntimeError("FindTourGo không trả tour — kiểm tra API hoặc mạng")
    n_co = df["cong_ty"].nunique() if "cong_ty" in df.columns else len(df)
    _emit(job_id, 72, f"Đã quét {len(df)} tour ({n_co} công ty) — ghi Sheet…")

    job.tours_total = len(df)
    db.commit()

    _emit(job_id, 85, f"Đang ghi {len(df)} tour lên tab FindTourGo…")
    write_to_google_sheet(df)
    _emit(job_id, 95, f"Đã ghi {len(df)} tour lên tab FindTourGo")
    return 0, len(df), 0


def _parse_price(raw: str) -> float | None:
    if not raw or str(raw).strip() in ("", "0", "nan"):
        return None
    cleaned = re.sub(r"[^\d]", "", str(raw))
    if not cleaned:
        return None
    val = float(cleaned)
    return val if val > 0 else None


def _parse_so_ngay(thoi_gian: str) -> float | None:
    if not thoi_gian or str(thoi_gian).strip() in ("", "nan"):
        return None
    s = str(thoi_gian).strip().lower()
    m = re.search(r"(?<!\d)(\d{1,2})\s*n", s)
    if m:
        d = float(m.group(1))
        return d if 0 < d <= 45 else None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*ng", s)
    if m:
        d = float(m.group(1).replace(",", "."))
        return d if 0 < d <= 45 else None
    return None


def _upsert_tours(db: Session, df, nguon: str, job_id: int, emit_job_id: int) -> tuple[int, int]:
    added, updated = 0, 0
    total = len(df)
    gia_col = "gia" if "gia" in df.columns else "gia_tu" if "gia_tu" in df.columns else None
    for i, (_, row) in enumerate(df.iterrows()):
        if i % 50 == 0:
            pct = 65 + int(20 * i / max(total, 1))
            _emit(emit_job_id, pct, f"Đang lưu {i}/{total}...")

        ma_tour = str(row.get("ma_tour") or row.get("page_code") or "").strip()
        gia_raw = str(row.get(gia_col) or "") if gia_col else ""
        gia = _parse_price(gia_raw)
        thoi_gian = str(row.get("thoi_gian") or "").strip()

        existing = None
        if ma_tour:
            existing = db.query(Tour).filter(Tour.ma_tour == ma_tour, Tour.nguon == nguon).first()

        from classification import resolve_company_name, resolve_departure_point
        from link_utils import normalize_tour_link

        data = dict(
            cong_ty=resolve_company_name(str(row.get("cong_ty") or "").strip())[:256],
            thi_truong=str(row.get("thi_truong") or "").strip(),
            tuyen_tour=str(row.get("tuyen_tour") or "").strip(),
            ten_tour=str(row.get("ten_tour") or "").strip(),
            lich_trinh=str(row.get("lich_trinh") or "").strip(),
            diem_kh=resolve_departure_point(str(row.get("diem_kh") or "").strip())[:256],
            thoi_gian=thoi_gian,
            gia_raw=gia_raw,
            gia=gia,
            lich_kh=str(row.get("lich_kh") or "").strip(),
            link_url=normalize_tour_link(str(row.get("link_url") or "").strip()),
            ma_tour=ma_tour,
            khach_san=str(row.get("khach_san") or "").strip(),
            hang_khong=str(row.get("hang_khong") or "").strip(),
            so_ngay=_parse_so_ngay(thoi_gian),
            phan_khuc="",
            nguon=nguon,
            scrape_job_id=job_id,
            updated_at=datetime.utcnow(),
        )

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            if not existing.external_id:
                from tour_identity import compute_external_id
                existing.external_id = compute_external_id(
                    nguon, ma_tour=ma_tour, link_url=data["link_url"], ten_tour=data["ten_tour"]
                )[:128]
            updated += 1
        else:
            from tour_identity import compute_external_id
            ext = compute_external_id(nguon, ma_tour=ma_tour, link_url=data["link_url"], ten_tour=data["ten_tour"])
            tour = Tour(**data, external_id=ext[:128], sheet_source=nguon)
            db.add(tour)
            added += 1

    db.commit()
    if added or updated:
        try:
            from pricing_segments import recompute_all_phan_khuc

            recompute_all_phan_khuc(db)
        except Exception:
            pass
    try:
        from compare_cache import invalidate_compare_cache
        invalidate_compare_cache()
    except Exception:
        pass
    return added, updated
