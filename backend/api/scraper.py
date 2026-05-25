from __future__ import annotations

import asyncio
import re
import sys
import threading
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user
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
    return (
        db.query(ScrapeJob)
        .order_by(ScrapeJob.started_at.desc())
        .limit(limit)
        .all()
    )


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
async def stream_job(job_id: int, _: User = Depends(get_current_user)):
    """SSE stream: client receives progress events until job completes."""

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

def _emit(job_id: int, pct: int, msg: str):
    import json
    payload = json.dumps({"pct": pct, "msg": msg, "done": False}, ensure_ascii=False)
    q = _progress_queues.get(job_id)
    if q:
        asyncio.run_coroutine_threadsafe(q.put(payload), _get_event_loop())


def _emit_done(job_id: int, added: int, updated: int):
    import json
    payload = json.dumps({"pct": 100, "msg": f"Hoàn thành: +{added} mới, ~{updated} cập nhật", "done": True, "added": added, "updated": updated})
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
    db = SessionLocal()
    try:
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if not job:
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        db.commit()

        _emit(job_id, 5, f"Bắt đầu quét {scraper_name}...")

        if scraper_name == "vietravel":
            added, updated = _run_vietravel(db, job_id, job)
        else:
            added, updated = _run_findtourgo(db, job_id, job)

        job.status = "success"
        job.progress_pct = 100
        job.tours_added = added
        job.tours_updated = updated
        job.finished_at = datetime.utcnow()
        db.commit()
        _emit_done(job_id, added, updated)

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

    _emit(job_id, 15, "Đang tải trang travel.com.vn...")
    df = scrape_all_vietravel_tours()
    _emit(job_id, 60, f"Đã quét {len(df)} tour, đang lưu vào database...")

    job.tours_total = len(df)
    db.commit()

    added, updated = _upsert_tours(db, df, "Vietravel", job.id, job_id)
    _emit(job_id, 85, "Đang sync lên Google Sheet...")
    try:
        from scrapers.vietravel_scraper import write_to_google_sheet
        write_to_google_sheet(df)
        _emit(job_id, 95, "Đã sync Google Sheet")
    except Exception as e:
        _emit(job_id, 95, f"Bỏ qua sync Sheet: {e}")

    return added, updated


def _run_findtourgo(db: Session, job_id: int, job: ScrapeJob):
    sys.path.insert(0, "scrapers")
    from scrapers.findtourgo_scraper import scrape_all_findtourgo_tours, write_to_google_sheet

    _emit(job_id, 15, "Đang kết nối FindTourGo API...")
    df = scrape_all_findtourgo_tours()
    _emit(job_id, 65, f"Đã quét {len(df)} tour từ {df['cong_ty'].nunique() if 'cong_ty' in df.columns else '?'} công ty, đang lưu...")

    job.tours_total = len(df)
    db.commit()

    added, updated = _upsert_tours(db, df, "FindTourGo", job.id, job_id)
    _emit(job_id, 88, "Đang sync lên Google Sheet...")
    try:
        write_to_google_sheet(df)
        _emit(job_id, 96, "Đã sync Google Sheet")
    except Exception as e:
        _emit(job_id, 96, f"Bỏ qua sync Sheet: {e}")

    return added, updated


def _parse_price(raw: str) -> float | None:
    if not raw or str(raw).strip() in ("", "0", "nan"):
        return None
    cleaned = re.sub(r"[^\d]", "", str(raw))
    if not cleaned:
        return None
    val = float(cleaned)
    return val if val > 0 else None


def _price_segment(gia: float | None) -> str:
    if gia is None:
        return "Chưa có giá"
    if gia < 2_000_000:
        return "Budget (< 2tr)"
    if gia < 5_000_000:
        return "Mid (2–5tr)"
    if gia < 15_000_000:
        return "Premium (5–15tr)"
    return "Luxury (> 15tr)"


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
            link_url=str(row.get("link_url") or "").strip(),
            ma_tour=ma_tour,
            khach_san=str(row.get("khach_san") or "").strip(),
            hang_khong=str(row.get("hang_khong") or "").strip(),
            so_ngay=_parse_so_ngay(thoi_gian),
            phan_khuc=_price_segment(gia),
            nguon=nguon,
            scrape_job_id=job_id,
            updated_at=datetime.utcnow(),
        )

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            updated += 1
        else:
            tour = Tour(**data)
            db.add(tour)
            added += 1

    db.commit()
    return added, updated
