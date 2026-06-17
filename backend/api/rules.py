from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy.orm import Session

from api.auth import require_admin
from classification import (
    apply_all_rules_to_tours,
    apply_company_aliases_to_tours,
    apply_departure_aliases_to_tours,
    apply_duration_aliases_to_tours,
    apply_classification_rules_to_tours,
    classification_rules_status,
    invalidate_classification_cache,
    invalidate_rules_changed,
    seed_company_aliases_from_defaults,
    seed_departure_aliases_from_defaults,
    seed_duration_aliases_from_defaults,
    seed_schedule_aliases_from_defaults,
    seed_market_rules_from_hardcode,
    seed_route_rules_from_bundle,
)
from database import get_db
from models import (
    CompanyAliasRule,
    DepartureAliasRule,
    DurationAliasRule,
    MarketKeywordRule,
    RouteKeywordRule,
    ScheduleAliasRule,
    Tour,
    User,
)
from sheets_rules_sync import (
    import_market_rules_from_sheet,
    import_route_rules_to_db,
    push_market_rules_to_sheet,
    push_route_rules_to_sheet,
    sync_all_from_sheet,
    sync_all_to_sheet,
)

router = APIRouter(prefix="/api/admin/rules", tags=["rules-admin"])


def _on_market_route_rules_changed(db: Session) -> None:
    """Sửa rule thị trường/tuyến → matcher mới + tour phải áp dụng lại."""
    invalidate_rules_changed(db)


def _after_alias_mutation(
    db: Session | None = None,
    field: str | None = None,
    value: str | None = None,
) -> None:
    """Sau khi POST/PUT/DELETE alias (company/departure/duration/schedule) — clear
    cache classification (_*_alias_pairs lru) + cập nhật cache unmatched (panel «Chưa khớp»).

    Hai chế độ cho cache unmatched:
    - Có (db, field, value) — sau CREATE alias: incremental remove — chỉ XÓA dòng
      ``value`` khỏi cache (rekey fingerprint mới) → panel GET sau INSTANT + đã mất
      dòng vừa gán, không full recompute (vài giây trên VPS 2vCPU).
      field: "cong_ty" | "diem_kh" | "thoi_gian" | "lich_kh".
    - Không args — UPDATE/DELETE rule: fallback invalidate toàn bộ (an toàn, vì
      sửa/xóa alias có thể làm value cũ QUAY LẠI panel — không thể remove-only).

    Classification lru cache LUÔN bị clear (rule pairs phải reload từ DB)."""
    from rules_job_store import invalidate_unmatched_cache, remove_from_unmatched_cache

    invalidate_classification_cache()
    try:
        if db is not None and field and value:
            remove_from_unmatched_cache(db, field, value)
        else:
            invalidate_unmatched_cache()
    except Exception:
        # cache layer optional — không chặn business logic nếu lỗi
        try:
            invalidate_unmatched_cache()
        except Exception:
            pass


def _targeted_alias_apply(db: Session, kind: str, alias: str) -> dict:
    """Targeted apply ngay sau khi gán alias — query hẹp (ILIKE %alias%, cap 2000),
    KHÔNG full scan → nhanh (<1s). Lỗi không chặn response (rule đã commit).

    Trả {"applied": N, "candidates": M, "capped": bool}."""
    from classification import apply_alias_rule_targeted

    # Resolver dùng _*_alias_pairs (lru) — phải clear TRƯỚC để thấy rule vừa insert.
    invalidate_classification_cache()
    try:
        return apply_alias_rule_targeted(db, kind, alias)
    except Exception as e:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "targeted alias apply failed (kind=%s, alias=%r): %s", kind, alias, e
        )
        return {"applied": 0, "candidates": 0, "capped": False, "error": str(e)[:200]}


def _alias_out_with_apply(model_cls, rule, apply_res: dict | None):
    """Build response Out từ ORM rule + gắn kết quả targeted apply (applied/capped)."""
    out = model_cls.model_validate(rule)
    if apply_res:
        out.applied = int(apply_res.get("applied") or 0)
        out.capped = bool(apply_res.get("capped"))
    return out


def _unmatched_tours_query(db: Session):
    """Query tour cho collect_unmatched_values — load_only đúng cột cần đọc.

    Cold path recompute panel «Chưa khớp» scan tour; trước đây load full row
    (lich_trinh/search_text/... Text lớn) → I/O nặng trên VPS 2vCPU. Cột liệt kê
    = đủ cho collect_unmatched_values (resolvers + matcher.resolve +
    is_stats_excluded_tour + is_vietravel_tab) — thêm cột mới nếu function đổi.

    KHÔNG filter theo DB_CANONICAL_NGUON: collect_unmatched_values gom alias cho
    CẢ tour FindTourGo (vtr_only=False). Text rác lệch cột như 'qatar airways',
    'du lịch maldives', 'khách sạn 4*...' nằm trên FTG cần hiện trong panel để
    admin chuẩn hóa. Filter canonical sẽ cắt mất chúng → regression panel rỗng."""
    from sqlalchemy.orm import load_only

    from models import Tour

    cols = load_only(
        Tour.id,
        Tour.nguon,
        Tour.sheet_source,   # is_vietravel_tab
        Tour.ten_tour,       # title hint + matcher + stats exclusions
        Tour.lich_trinh,     # matcher.resolve
        Tour.thi_truong,
        Tour.tuyen_tour,
        Tour.cong_ty,        # alias company
        Tour.diem_kh,        # alias departure
        Tour.thoi_gian,      # alias duration
        Tour.so_ngay,
        Tour.lich_kh,        # alias schedule + DateFormatRule DSL
        Tour.link_url,       # member tour link (panel «Chưa khớp» hiện link để check)
    )
    return (
        db.query(Tour)
        .options(cols)
        .yield_per(800)
    )


@router.get("/status")
def rules_runtime_status(_: User = Depends(require_admin)):
    """Nguồn alias đang dùng lúc chạy (DB vs mặc định code khi bảng trống)."""
    return classification_rules_status()


class MarketRuleOut(BaseModel):
    id: int
    market: str
    keyword: str
    active: bool
    sort_order: int
    model_config = {"from_attributes": True}

    @field_serializer("id")
    def _ser_id(self, v: int) -> str:
        # CockroachDB unique_rowid() ~1.18e18 > 2^53 (JS Number.MAX_SAFE_INTEGER) →
        # browser tự làm tròn → DELETE /rules/market/<wrong_id> trả 404.
        # Cùng pattern với ScrapeJob.JobOut (commit 1d3ded1).
        return str(v)


class MarketRuleIn(BaseModel):
    market: str = Field(max_length=128)
    keyword: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


class RouteRuleOut(BaseModel):
    id: int
    thi_truong: str
    tuyen_tour: str
    keywords: str
    active: bool
    priority: bool = False
    sort_order: int
    model_config = {"from_attributes": True}

    @field_serializer("id")
    def _ser_id(self, v: int) -> str:
        # CockroachDB id > 2^53 → JS rounds → DELETE /rules/route/<wrong_id> = 404.
        return str(v)


class RouteRuleIn(BaseModel):
    thi_truong: str = Field(max_length=128)
    tuyen_tour: str = Field(max_length=256)
    keywords: str = Field(max_length=512, description="Các từ khóa cách nhau bởi dấu phẩy, TẤT CẢ phải có trong tên tour")
    active: bool = True
    priority: bool = False
    sort_order: int = 0


class RouteRulePriorityIn(BaseModel):
    priority: bool


class RouteRulesReplaceIn(BaseModel):
    rules: list[RouteRuleIn]
    market_order: list[str] = Field(default_factory=list)
    auto_apply: bool = False


class AssignClassificationIn(BaseModel):
    thi_truong: str = Field(max_length=128)
    tuyen_tour: str = Field(default="", max_length=256)
    route_keywords: str = Field(
        max_length=512,
        description="Một dòng rule mới (OR). Trong dòng: dấu phẩy = AND.",
    )
    market_keyword: str = Field(default="", max_length=256, description="Để trống = lấy từ keyword tuyến đầu tiên")
    auto_apply: bool = False  # default False — user bấm "Áp dụng lên tour" thủ công sau khi sửa


class BulkAssignClassificationItem(BaseModel):
    thi_truong: str = Field(max_length=128)
    tuyen_tour: str = Field(default="", max_length=256)
    route_keywords: str = Field(max_length=512)


class BulkAssignClassificationIn(BaseModel):
    items: list[BulkAssignClassificationItem] = Field(min_length=1, max_length=100)
    auto_apply: bool = False  # default False — user bấm "Áp dụng lên tour" thủ công sau khi sửa


def _add_route_rule_row(db: Session, mk: str, route: str, route_kws: str) -> bool:
    """Thêm dòng rule OR nếu chưa có cùng bộ keyword. Trả về True nếu đã thêm."""
    from classification import merge_keyword_csv

    siblings = (
        db.query(RouteKeywordRule)
        .filter(
            RouteKeywordRule.thi_truong == mk,
            RouteKeywordRule.tuyen_tour == route,
            RouteKeywordRule.active == True,
        )
        .all()
    )
    if any(merge_keyword_csv(r.keywords, "") == route_kws for r in siblings):
        return False
    next_order = max((r.sort_order for r in siblings), default=-1) + 1
    db.add(
        RouteKeywordRule(
            thi_truong=mk,
            tuyen_tour=route,
            keywords=route_kws,
            sort_order=next_order,
        )
    )
    return True


def _try_push_market(db: Session) -> str | None:
    try:
        n = push_market_rules_to_sheet(db)
        return f"Đã ghi {n} rule thị trường lên Sheet"
    except Exception as e:
        return f"Cảnh báo: không ghi được Sheet thị trường — {e}"


def _try_push_route(db: Session) -> str | None:
    try:
        n = push_route_rules_to_sheet(db)
        return f"Đã ghi {n} rule tuyến tour lên Sheet"
    except Exception as e:
        return f"Cảnh báo: không ghi được Sheet tuyến tour — {e}"


def _auto_apply_tours(
    db: Session,
    enabled: bool,
    scope: str = "all",
    *,
    keywords: list[str] | None = None,
) -> dict | None:
    """
    Áp dụng quy tắc lên tour.
    Có keywords (sau Gán / sửa rule) → chạy đồng bộ trên tour liên quan, trả kết quả ngay.
    Không keywords → chạy nền (full scan).
    """
    if not enabled:
        return None

    if keywords and scope in ("market", "route", "all"):
        from classification import apply_classification_for_keywords
        from rules_job_store import invalidate_unmatched_cache

        try:
            result = apply_classification_for_keywords(db, keywords)
            invalidate_unmatched_cache()
            msg = result.get("message") or (
                f"Đã cập nhật {int(result.get('route_updated') or 0)} tour "
                f"(quét {int(result.get('tours_scanned') or 0)} tour có keyword)"
            )
            return {
                "started": False,
                "applied": True,
                "sync": True,
                "message": msg,
                "result": result,
            }
        except RuntimeError as e:
            # Lock busy: tours_write đang bị job khác giữ. Thay vì 500, đẩy sang
            # background worker (debounce) — worker sẽ retry sau khi lock free.
            # UI nhận "Đang áp dụng nền" thay vì error đỏ.
            if "đang có job khác" in str(e).lower():
                import logging
                logging.getLogger(__name__).info(
                    "sync apply busy → defer to background worker (scope=%s, keywords=%s)",
                    scope, keywords,
                )
                _request_background_apply(scope)
                return {
                    "started": True,
                    "applied": False,
                    "sync": False,
                    "message": "Đang đợi job khác xong rồi áp dụng nền — không cần làm gì thêm.",
                }
            raise  # other RuntimeError: bubble up
        except Exception as e:
            import logging

            logging.getLogger(__name__).exception("sync apply after assign failed: %s", e)
            raise HTTPException(500, f"Gán rule xong nhưng áp dụng tour thất bại: {e}") from e

    _request_background_apply(scope)
    return {"started": True, "message": "Đang áp dụng quy tắc lên tour (chạy nền)…"}


# Debounce state cho apply background — KHÔNG spawn nhiều thread cùng lúc khi user xóa
# nhiều rule liên tiếp. Nếu thread hiện tại đang chạy, các trigger sau chỉ set flag;
# thread sẽ kiểm tra flag sau khi xong và chạy thêm 1 lần nếu cần.
import threading as _threading
import time as _time

_apply_state_lock = _threading.Lock()
_apply_pending_scopes: set[str] = set()
_apply_thread: _threading.Thread | None = None

# RU budget protection: limit số lần apply chạy trong 1 cửa sổ thời gian.
# Render log 2026-06-07: bulk rule import → loop chạy liên tục ~10 phút → 98M RU/h
# (~25% monthly budget). Giới hạn tối đa 3 lần apply mỗi 10 phút; vượt → bỏ qua,
# user dùng "Áp dụng lên tour" thủ công hoặc apply_rules_offline.py.
_APPLY_MAX_RUNS_PER_WINDOW = 3
_APPLY_WINDOW_SEC = 600.0
_apply_run_timestamps: list[float] = []


def _request_background_apply(scope: str) -> None:
    """Đảm bảo có đúng 1 thread đang xử lý apply. Trigger nhiều lần → gộp 1 lần chạy."""
    global _apply_thread
    with _apply_state_lock:
        _apply_pending_scopes.add(scope)
        if _apply_thread is not None and _apply_thread.is_alive():
            return  # thread đang chạy sẽ tự pick up scope mới qua _apply_pending_scopes
        _apply_thread = _threading.Thread(
            target=_apply_worker_loop, daemon=True, name="apply-rules-debounce",
        )
        _apply_thread.start()


def _apply_worker_loop() -> None:
    """Loop pop scope → chạy apply → repeat đến hết pending.

    Nếu lock_busy (job khác đang ghi tour) → log INFO không phải ERROR, retry 1 lần
    sau 5s rồi bỏ; user vẫn có thể bấm "Áp dụng lên tour" thủ công."""
    import logging
    from database import SessionLocal

    log = logging.getLogger(__name__)
    lock_busy_retries = 0

    while True:
        with _apply_state_lock:
            if not _apply_pending_scopes:
                return
            # RU budget: nếu đã chạy >= N lần trong window → bỏ pending, exit.
            now_ts = _time.monotonic()
            global _apply_run_timestamps
            _apply_run_timestamps = [t for t in _apply_run_timestamps if now_ts - t < _APPLY_WINDOW_SEC]
            if len(_apply_run_timestamps) >= _APPLY_MAX_RUNS_PER_WINDOW:
                log.warning(
                    "apply-rules: vượt %d lần/%ds (RU budget) → bỏ %s. User chạy thủ công sau.",
                    _APPLY_MAX_RUNS_PER_WINDOW, int(_APPLY_WINDOW_SEC), _apply_pending_scopes,
                )
                _apply_pending_scopes.clear()
                return
            _apply_run_timestamps.append(now_ts)
            # "all" cover mọi scope khác — ưu tiên gộp
            scope = "all" if "all" in _apply_pending_scopes else next(iter(_apply_pending_scopes))
            _apply_pending_scopes.clear()

        session = SessionLocal()
        success = False
        try:
            # Flush throttled UPDATE classified_at trước khi apply chạy.
            # Bulk rule changes có thể đã set pending flag mà chưa kịp clear.
            from classification import flush_pending_rules_invalidate
            try:
                flush_pending_rules_invalidate(session)
            except Exception as _flush_err:  # noqa: BLE001
                log.warning("flush pending invalidate failed: %s", _flush_err)

            if scope in ("market", "route", "all"):
                from classification import apply_classification_rules_to_tours
                apply_classification_rules_to_tours(session)
            elif scope == "company":
                apply_company_aliases_to_tours(session)
            elif scope == "departure":
                apply_departure_aliases_to_tours(session)
            elif scope == "duration":
                apply_duration_aliases_to_tours(session)
            elif scope == "schedule":
                # Lich_kh không có apply-to-tours (Tour.lich_kh giữ nguyên text gốc;
                # alias chỉ ảnh hưởng collect_unmatched_values). Chỉ invalidate cache.
                invalidate_classification_cache()
            else:
                apply_all_rules_to_tours(session)
            success = True
            lock_busy_retries = 0  # reset sau khi chạy thành công
        except RuntimeError as e:
            if "đang có job khác" in str(e).lower() and lock_busy_retries < 1:
                # Lock contention — re-queue 1 lần, không log ERROR.
                lock_busy_retries += 1
                with _apply_state_lock:
                    _apply_pending_scopes.add(scope)
                log.info(
                    "apply-rules: lock đang bận, retry %d/1 sau 5s (scope=%s)",
                    lock_busy_retries, scope,
                )
                session.close()
                _time.sleep(5)
                continue
            # Đã retry rồi hoặc lỗi khác — log info (không phải error) rồi bỏ
            log.info("apply-rules: bỏ qua (%s); user có thể bấm Áp dụng thủ công", e)
            lock_busy_retries = 0
        except Exception as e:  # noqa: BLE001
            log.exception("apply-rules failed scope=%s: %s", scope, e)
            lock_busy_retries = 0
        finally:
            try:
                invalidate_classification_cache()
                from rules_job_store import invalidate_unmatched_cache
                invalidate_unmatched_cache()
            except Exception:  # noqa: BLE001
                pass
            session.close()
        # Loop sẽ check pending lần nữa — nếu user thêm flag trong lúc đang chạy → tiếp tục
        if not success and lock_busy_retries == 0:
            # Tránh tight loop nếu có lỗi liên tục
            _time.sleep(1)


def _start_apply_all_rules_background(*, recompute_phan_khuc: bool = False, incremental: bool = True) -> dict:
    """Full apply — chạy nền, trạng thái lưu Supabase (app_kv)."""
    import logging
    from datetime import datetime, timezone

    from rules_job_store import get_apply_status, set_apply_status

    log = logging.getLogger(__name__)
    st = get_apply_status()
    if st.get("running"):
        return {
            "started": False,
            "running": True,
            "message": "Đang áp dụng quy tắc lên tour (job trước chưa xong)…",
        }

    params = {
        "incremental": bool(incremental),
        "recompute_phan_khuc": bool(recompute_phan_khuc),
    }
    can_resume = bool(st.get("stale")) and st.get("params") == params
    resume_from_id = int(st.get("last_id") or 0) if can_resume else 0
    initial_processed = int(st.get("progress") or 0) if can_resume else 0
    total_override = int(st.get("total") or 0) if can_resume and st.get("total") is not None else None
    started_at = datetime.now(timezone.utc).isoformat()
    set_apply_status({
        "running": True,
        "started_at": started_at,
        "progress": initial_processed,
        "last_id": resume_from_id,
        "params": params,
        "message": "Đang áp dụng quy tắc…",
    })

    def _work() -> None:
        from database import SessionLocal

        session = SessionLocal()

        def _progress(n: int, total: int, msg: str, last_id: int | None = None) -> None:
            from datetime import datetime, timezone

            set_apply_status({
                "running": True,
                "started_at": started_at,
                "progress_at": datetime.now(timezone.utc).isoformat(),
                "progress": n,
                "total": total,
                "last_id": last_id,
                "params": params,
                "message": msg,
            })

        try:
            result = apply_all_rules_to_tours(
                session,
                recompute_phan_khuc=recompute_phan_khuc,
                incremental=incremental,
                start_after_id=resume_from_id,
                initial_processed=initial_processed,
                total_override=total_override,
                progress_cb=_progress,
            )
            log.info("apply_all_rules_to_tours finished: %s", result.get("message"))
            set_apply_status({
                "running": False,
                "last_result": result,
                "message": result.get("message", "Đã áp dụng quy tắc lên tour"),
            })
        except Exception as e:
            log.exception("apply_all_rules_to_tours failed")
            set_apply_status({
                "running": False,
                "error": str(e)[:500],
                "message": f"Áp dụng thất bại: {e}",
            })
        finally:
            session.close()

    threading.Thread(target=_work, daemon=True, name="apply-rules-all").start()
    return {
        "started": True,
        "running": True,
        "message": "Đã bắt đầu áp dụng quy tắc lên tour (một lượt quét, ~30s–2 phút).",
    }


# ── Market rules ──────────────────────────────────────────────────────────────

@router.get("/market", response_model=list[MarketRuleOut])
def list_market_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(MarketKeywordRule).order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id).all()


@router.post("/market", response_model=MarketRuleOut)
def create_market_rule(
    body: MarketRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = MarketKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)
    if push_sheet:
        _try_push_market(db)
    _auto_apply_tours(db, auto_apply, scope="market")
    return rule


@router.patch("/market/{rule_id}", response_model=MarketRuleOut)
def update_market_rule(
    rule_id: int,
    body: MarketRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)
    if push_sheet:
        _try_push_market(db)
    _auto_apply_tours(db, auto_apply, scope="market")
    return rule


@router.delete("/market/{rule_id}")
def delete_market_rule(
    rule_id: int,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")

    # Wrap commit trong run_with_retry — CockroachDB Serializable mode hay throw
    # 40001 SerializationFailure khi DELETE chạm contention với scrape/sync khác
    # (Render log 2026-06-07: id=827 ABORT_REASON_PUSHER_ABORTED).
    from db_retry import run_with_retry

    def _do():
        db.rollback()  # session fresh cho mỗi attempt
        r = db.query(MarketKeywordRule).filter(MarketKeywordRule.id == rule_id).first()
        if r is None:
            return  # idempotent: lần thử trước đã xóa thành công
        db.delete(r)
        db.commit()

    run_with_retry(_do, db=db, label="delete-market-rule")
    _on_market_route_rules_changed(db)
    msg = _try_push_market(db) if push_sheet else None
    stats = _auto_apply_tours(db, auto_apply, scope="market")
    return {"deleted": rule_id, "sheet_sync": msg, "tours_apply": stats}


# ── Route rules ───────────────────────────────────────────────────────────────

@router.get("/route", response_model=list[RouteRuleOut])
def list_route_rules(
    thi_truong: str = "",
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(RouteKeywordRule)
    if thi_truong:
        q = q.filter(RouteKeywordRule.thi_truong == thi_truong)
    return q.order_by(RouteKeywordRule.sort_order, RouteKeywordRule.id).all()


@router.post("/route/replace-all")
def replace_all_route_rules(
    body: RouteRulesReplaceIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Thay toàn bộ quy tắc tuyến tour trong DB (import Excel/JSON)."""
    from classification_rules_import import replace_route_rules

    rows = [r.model_dump() for r in body.rules]
    try:
        result = replace_route_rules(db, rows, body.market_order or None)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    tours_apply = _auto_apply_tours(db, body.auto_apply, scope="route")
    return {**result, "tours_apply": tours_apply}


@router.post("/route", response_model=RouteRuleOut)
def create_route_rule(
    body: RouteRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = RouteKeywordRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)
    if push_sheet:
        _try_push_route(db)
    kws = [k.strip().lower() for k in rule.keywords.split(",") if k.strip()]
    _auto_apply_tours(db, auto_apply, scope="route", keywords=kws or None)
    return rule


@router.patch("/route/{rule_id}", response_model=RouteRuleOut)
def update_route_rule(
    rule_id: int,
    body: RouteRuleIn,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)
    if push_sheet:
        _try_push_route(db)
    kws = [k.strip().lower() for k in rule.keywords.split(",") if k.strip()]
    _auto_apply_tours(db, auto_apply, scope="route", keywords=kws or None)
    return rule


@router.patch("/route/{rule_id}/priority", response_model=RouteRuleOut)
def set_route_rule_priority(
    rule_id: int,
    body: RouteRulePriorityIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Bật/tắt ưu tiên (priority) cho rule — không cần auto_apply vì không đổi keywords."""
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")
    rule.priority = body.priority
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)  # reload matcher với priority mới
    return rule


@router.delete("/route/{rule_id}")
def delete_route_rule(
    rule_id: int,
    push_sheet: bool = Query(False),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Không tìm thấy rule")

    # Wrap detach + delete trong 1 retry-able transaction.
    # Trước đây 2 commit riêng → nếu attempt 1 detach OK rồi delete fail (40001
    # SerializationFailure như Render log 2026-06-07 id=827 ABORT_REASON_PUSHER_ABORTED),
    # tours bị detach nhưng rule chưa xóa → trạng thái nửa vời. Gộp 1 commit + retry.
    from db_retry import run_with_retry

    detached_count = 0

    def _do():
        nonlocal detached_count
        db.rollback()
        r = db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()
        if r is None:
            detached_count = 0
            return  # idempotent
        # Detach tours đang reference rule (FK tours_classification_rule_id_fkey).
        detached_count = (
            db.query(Tour)
            .filter(Tour.classification_rule_id == rule_id)
            .update({Tour.classification_rule_id: None, Tour.classified_at: None}, synchronize_session=False)
        )
        db.delete(r)
        db.commit()

    run_with_retry(_do, db=db, label="delete-route-rule")
    _on_market_route_rules_changed(db)
    msg = _try_push_route(db) if push_sheet else None
    stats = _auto_apply_tours(db, auto_apply, scope="route")
    return {"deleted": rule_id, "detached_tours": detached_count, "sheet_sync": msg, "tours_apply": stats}


# ── Sync endpoints ────────────────────────────────────────────────────────────

@router.post("/seed-market-defaults")
def seed_market_defaults(
    push_sheet: bool = Query(True),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    count = seed_market_rules_from_hardcode()
    msg = None
    if push_sheet and count >= 0:
        msg = _try_push_market(db)
    return {
        "imported": count,
        "message": f"Đã import {count} keyword mặc định" if count else "DB đã có rules",
        "sheet_sync": msg,
    }


@router.post("/seed-route-defaults")
def seed_route_defaults(
    auto_apply: bool = Query(False),
    force: bool = Query(False, description="Ghi đè toàn bộ rule tuyến trong DB bằng bản bundle"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Nạp quy tắc tuyến từ bundle JSON vào Supabase (không đọc Google Sheet)."""
    count = seed_route_rules_from_bundle(db, force=force)
    tours = _auto_apply_tours(db, auto_apply, scope="route") if count else None
    return {
        "imported": count,
        "message": f"Đã nạp {count} rule tuyến tour vào DB" if count else "DB đã có rules (bỏ qua)",
        "tours_apply": tours,
    }


@router.post("/sync-route-from-sheet")
def sync_route_from_sheet(
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        count = import_route_rules_to_db(db)
        tours = _auto_apply_tours(db, auto_apply, scope="route")
        return {"imported": count, "message": f"Đã kéo {count} rule tuyến tour từ Sheet → DB", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đọc Google Sheet: {e}") from e


@router.post("/sync-route-to-sheet")
def sync_route_to_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = push_route_rules_to_sheet(db)
        return {"pushed": count, "message": f"Đã ghi {count} rule tuyến tour từ DB → Sheet 'Điểm tuyến Tour'"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi ghi Google Sheet: {e}") from e


@router.post("/sync-market-from-sheet")
def sync_market_from_sheet(
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        count = import_market_rules_from_sheet(db)
        tours = _auto_apply_tours(db, auto_apply, scope="market")
        return {"imported": count, "message": f"Đã kéo {count} rule thị trường từ Sheet → DB", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đọc Google Sheet: {e}") from e


@router.post("/sync-market-to-sheet")
def sync_market_to_sheet(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        count = push_market_rules_to_sheet(db)
        return {"pushed": count, "message": f"Đã ghi {count} rule thị trường từ DB → Sheet 'Quy tắc Thị trường'"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi ghi Google Sheet: {e}") from e


@router.post("/sync-all-from-sheet")
def sync_all_from_sheet_endpoint(
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        result = sync_all_from_sheet(db)
        tours = _auto_apply_tours(db, auto_apply, scope="all")
        return {**result, "message": "Đã đồng bộ Sheet → DB (thị trường + tuyến tour)", "tours_apply": tours}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ từ Sheet: {e}") from e


@router.post("/sync-all-to-sheet")
def sync_all_to_sheet_endpoint(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        result = sync_all_to_sheet(db)
        return {**result, "message": "Đã đồng bộ DB → Sheet (thị trường + tuyến tour)"}
    except Exception as e:
        raise HTTPException(502, f"Lỗi đồng bộ lên Sheet: {e}") from e


# ── Company alias rules ──────────────────────────────────────────────────────

class _RuleIdAsStrMixin:
    """Serialize id field as string — applied to Company/Departure/Duration rule outputs."""

    @field_serializer("id")
    def _ser_id(self, v: int) -> str:
        return str(v)


class CompanyRuleOut(_RuleIdAsStrMixin, BaseModel):
    id: int
    canonical_name: str
    alias: str
    active: bool
    sort_order: int
    # Targeted apply sau Gán: số tour đã cập nhật ngay + capped=True nếu còn tour
    # vượt cap 2000 (cron/apply-to-tours xử lý tiếp). Frontend toast "áp dụng cho N tour".
    applied: int = 0
    capped: bool = False
    model_config = {"from_attributes": True}


class CompanyRuleIn(BaseModel):
    canonical_name: str = Field(max_length=128)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/company", response_model=list[CompanyRuleOut])
def list_company_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(CompanyAliasRule)
        .order_by(CompanyAliasRule.sort_order, CompanyAliasRule.canonical_name, CompanyAliasRule.alias)
        .all()
    )


@router.post("/company", response_model=CompanyRuleOut)
def create_company_rule(
    body: CompanyRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = CompanyAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    # Targeted apply: chỉ tour có cong_ty chứa alias (cap 2000) — tour hiệu lực ngay.
    apply_res = _targeted_alias_apply(db, "company", alias_val)
    # Incremental: xóa đúng dòng alias khỏi cache panel «Chưa khớp» (instant).
    _after_alias_mutation(db, "cong_ty", alias_val)
    _auto_apply_tours(db, auto_apply, scope="company")
    return _alias_out_with_apply(CompanyRuleOut, rule, apply_res)


@router.put("/company/{rule_id}", response_model=CompanyRuleOut)
def update_company_rule(
    rule_id: int,
    body: CompanyRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(CompanyAliasRule).filter(CompanyAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    apply_res = _targeted_alias_apply(db, "company", alias_val)
    # Update có thể làm value cũ QUAY LẠI panel → full invalidate (an toàn).
    _after_alias_mutation()
    _auto_apply_tours(db, auto_apply, scope="company")
    return _alias_out_with_apply(CompanyRuleOut, rule, apply_res)


@router.delete("/company/{rule_id}")
def delete_company_rule(
    rule_id: int,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(CompanyAliasRule).filter(CompanyAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    _after_alias_mutation()
    stats = _auto_apply_tours(db, auto_apply, scope="company")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/company/seed-defaults")
def seed_company_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_company_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias mặc định"}


@router.post("/company/apply-to-tours")
def apply_company_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_company_aliases_to_tours(db)
    return {"updated": updated, "message": f"Đã chuẩn hóa tên công ty cho {updated} tour"}


# ── Departure alias rules (Điểm KH) ──────────────────────────────────────────

class DepartureRuleOut(_RuleIdAsStrMixin, BaseModel):
    id: int
    canonical_name: str
    alias: str
    active: bool
    sort_order: int
    # Targeted apply sau Gán (xem CompanyRuleOut).
    applied: int = 0
    capped: bool = False
    model_config = {"from_attributes": True}


class DepartureRuleIn(BaseModel):
    canonical_name: str = Field(max_length=128)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/departure", response_model=list[DepartureRuleOut])
def list_departure_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(DepartureAliasRule)
        .order_by(DepartureAliasRule.sort_order, DepartureAliasRule.canonical_name, DepartureAliasRule.alias)
        .all()
    )


@router.post("/departure", response_model=DepartureRuleOut)
def create_departure_rule(
    body: DepartureRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = DepartureAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    # Targeted apply: tour có diem_kh chứa alias → resolve_departure_point per-tour
    # (giữ nguyên multi-leg preserve logic), cap 2000.
    apply_res = _targeted_alias_apply(db, "departure", alias_val)
    _after_alias_mutation(db, "diem_kh", alias_val)
    _auto_apply_tours(db, auto_apply, scope="departure")
    return _alias_out_with_apply(DepartureRuleOut, rule, apply_res)


@router.put("/departure/{rule_id}", response_model=DepartureRuleOut)
def update_departure_rule(
    rule_id: int,
    body: DepartureRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DepartureAliasRule).filter(DepartureAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    apply_res = _targeted_alias_apply(db, "departure", alias_val)
    # Update → full invalidate (value cũ có thể quay lại panel).
    _after_alias_mutation()
    _auto_apply_tours(db, auto_apply, scope="departure")
    return _alias_out_with_apply(DepartureRuleOut, rule, apply_res)


@router.delete("/departure/{rule_id}")
def delete_departure_rule(
    rule_id: int,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DepartureAliasRule).filter(DepartureAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    _after_alias_mutation()
    stats = _auto_apply_tours(db, auto_apply, scope="departure")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/departure/seed-defaults")
def seed_departure_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_departure_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias điểm KH mặc định"}


@router.post("/departure/apply-to-tours")
def apply_departure_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_departure_aliases_to_tours(db)
    return {"updated": updated, "message": f"Đã chuẩn hóa điểm khởi hành cho {updated} tour"}


@router.post("/apply-classification-to-tours")
def apply_classification_endpoint(
    recompute_phan_khuc: bool = Query(False, description="Tính lại phân khúc toàn DB (chậm)"),
    full_scan: bool = Query(False, description="Quét lại toàn bộ ~9k tour (mặc định: chỉ tour mới/cần cập nhật)"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Áp dụng quy tắc — async (tránh HTTP 503 khi ~8k tour)."""
    return _start_apply_all_rules_background(
        recompute_phan_khuc=recompute_phan_khuc,
        incremental=not full_scan,
    )


@router.get("/apply-classification-status")
def apply_classification_status(_: User = Depends(require_admin)):
    from rules_job_store import get_apply_status

    st = get_apply_status()
    out: dict = {"running": bool(st.get("running"))}
    if st.get("message"):
        out["message"] = st["message"]
    if st.get("progress") is not None:
        out["progress"] = st["progress"]
    if st.get("total") is not None:
        out["total"] = st["total"]
    if st.get("last_id") is not None:
        out["last_id"] = st["last_id"]
    if st.get("stale") is not None:
        out["stale"] = bool(st.get("stale"))
    if st.get("params"):
        out["params"] = st["params"]
    if st.get("last_result"):
        out["last_result"] = st["last_result"]
    if st.get("error"):
        out["error"] = st["error"]
    return out


# ── Duration alias rules (Thời gian) ─────────────────────────────────────────

class DurationRuleOut(_RuleIdAsStrMixin, BaseModel):
    id: int
    canonical_days: float
    alias: str
    active: bool
    sort_order: int
    # Targeted apply sau Gán (xem CompanyRuleOut).
    applied: int = 0
    capped: bool = False
    model_config = {"from_attributes": True}


class DurationRuleIn(BaseModel):
    canonical_days: float = Field(gt=0, le=45)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/duration", response_model=list[DurationRuleOut])
def list_duration_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(DurationAliasRule)
        .order_by(DurationAliasRule.sort_order, DurationAliasRule.canonical_days, DurationAliasRule.alias)
        .all()
    )


@router.post("/duration", response_model=DurationRuleOut)
def create_duration_rule(
    body: DurationRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = DurationAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    # Targeted apply: tour có thoi_gian chứa alias → recompute so_ngay (skip manual_locked).
    apply_res = _targeted_alias_apply(db, "duration", alias_val)
    _after_alias_mutation(db, "thoi_gian", alias_val)
    _auto_apply_tours(db, auto_apply, scope="duration")
    return _alias_out_with_apply(DurationRuleOut, rule, apply_res)


@router.put("/duration/{rule_id}", response_model=DurationRuleOut)
def update_duration_rule(
    rule_id: int,
    body: DurationRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DurationAliasRule).filter(DurationAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    alias_val = rule.alias
    apply_res = _targeted_alias_apply(db, "duration", alias_val)
    # Update → full invalidate (value cũ có thể quay lại panel).
    _after_alias_mutation()
    _auto_apply_tours(db, auto_apply, scope="duration")
    return _alias_out_with_apply(DurationRuleOut, rule, apply_res)


@router.delete("/duration/{rule_id}")
def delete_duration_rule(
    rule_id: int,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(DurationAliasRule).filter(DurationAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    _after_alias_mutation()
    stats = _auto_apply_tours(db, auto_apply, scope="duration")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/duration/seed-defaults")
def seed_duration_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_duration_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias thời gian mặc định"}


@router.post("/duration/apply-to-tours")
def apply_duration_rules_to_tours(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    updated = apply_duration_aliases_to_tours(db)
    # so_ngay đổi → giá/ngày đổi → phân khúc phải tính lại. Đồng thời FILL phân khúc
    # cho tour còn trống ("—"). Invalidate route_avg vì so_ngay là mẫu số của giá TB.
    filled = 0
    try:
        from pricing_segments import invalidate_route_avg_cache, recompute_missing_phan_khuc
        invalidate_route_avg_cache()
        filled = recompute_missing_phan_khuc(db)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("recompute phan_khuc after duration apply failed: %s", e)
    msg = f"Đã chuẩn hóa số ngày cho {updated} tour"
    if filled:
        msg += f" · điền phân khúc {filled} tour"
    return {"updated": updated, "phan_khuc_filled": filled, "message": msg}


# ── Schedule alias rules (Ngày KH / lich_kh) ─────────────────────────────────

class ScheduleRuleOut(_RuleIdAsStrMixin, BaseModel):
    id: int
    canonical_name: str
    alias: str
    active: bool
    sort_order: int
    # Schedule alias KHÔNG ghi field tour (chỉ dùng lúc parse/thống kê) → applied luôn 0.
    # Field giữ cho đồng nhất shape với company/departure/duration.
    applied: int = 0
    capped: bool = False
    model_config = {"from_attributes": True}


class ScheduleRuleIn(BaseModel):
    # canonical_name có thể RỖNG = đánh dấu "bỏ qua tour khỏi thống kê tần suất đoàn".
    canonical_name: str = Field(default="", max_length=128)
    alias: str = Field(max_length=256)
    active: bool = True
    sort_order: int = 0


@router.get("/schedule", response_model=list[ScheduleRuleOut])
def list_schedule_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return (
        db.query(ScheduleAliasRule)
        .order_by(ScheduleAliasRule.sort_order, ScheduleAliasRule.canonical_name, ScheduleAliasRule.alias)
        .all()
    )


@router.post("/schedule", response_model=ScheduleRuleOut)
def create_schedule_rule(
    body: ScheduleRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = ScheduleAliasRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    # Schedule alias KHÔNG ghi field tour (chỉ dùng lúc parse/thống kê lich_kh)
    # → không targeted apply; chỉ incremental remove khỏi panel «Chưa khớp».
    _after_alias_mutation(db, "lich_kh", rule.alias)
    _auto_apply_tours(db, auto_apply, scope="schedule")
    return rule


@router.put("/schedule/{rule_id}", response_model=ScheduleRuleOut)
def update_schedule_rule(
    rule_id: int,
    body: ScheduleRuleIn,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(ScheduleAliasRule).filter(ScheduleAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    _after_alias_mutation()
    _auto_apply_tours(db, auto_apply, scope="schedule")
    return rule


@router.delete("/schedule/{rule_id}")
def delete_schedule_rule(
    rule_id: int,
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rule = db.query(ScheduleAliasRule).filter(ScheduleAliasRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    _after_alias_mutation()
    stats = _auto_apply_tours(db, auto_apply, scope="schedule")
    return {"deleted": rule_id, "tours_apply": stats}


@router.post("/schedule/seed-defaults")
def seed_schedule_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    added = seed_schedule_aliases_from_defaults()
    return {"added": added, "message": f"Đã thêm {added} alias lịch khởi hành mặc định"}


# ── Date format rules (pattern-based parser cho lich_kh) ─────────────────────


class DateFormatRuleOut(_RuleIdAsStrMixin, BaseModel):
    id: int
    pattern: str
    output_type: str
    output_value: str | None = None
    priority: int
    active: bool
    description: str
    model_config = {"from_attributes": True}


class DateFormatRuleIn(BaseModel):
    # Pattern DSL: {dd} {mm} {yyyy} {yy} {weekday} {...} + literal text
    pattern: str = Field(min_length=1, max_length=512)
    # Loại output: dates | weekly | monthly_recurring | skip | verbatim | explicit_dates
    output_type: str = Field(max_length=32)
    # Chỉ dùng khi output_type='explicit_dates' — user nhập list ngày đầy đủ
    # vd "25/06/2026, 28/07/2026". Bỏ qua khi output_type khác.
    output_value: str | None = Field(default=None, max_length=512)
    priority: int = Field(default=100, ge=1, le=10_000)
    active: bool = True
    description: str = Field(default="", max_length=256)


_VALID_OUTPUT_TYPES = {"dates", "weekly", "monthly_recurring", "skip", "verbatim", "explicit_dates"}


def _validate_date_format_rule(body: DateFormatRuleIn) -> None:
    if body.output_type not in _VALID_OUTPUT_TYPES:
        raise HTTPException(
            400,
            f"output_type không hợp lệ ({body.output_type}); cho phép: {sorted(_VALID_OUTPUT_TYPES)}",
        )
    # explicit_dates yêu cầu output_value phải parse ra ít nhất 1 ngày
    if body.output_type == "explicit_dates":
        from date_format_rules import _parse_explicit_dates_string, _today
        parsed = _parse_explicit_dates_string(body.output_value or "", _today())
        if not parsed:
            raise HTTPException(
                400,
                "explicit_dates yêu cầu output_value chứa ít nhất 1 ngày DD/MM/YYYY "
                "(vd '25/06/2026, 28/07/2026')",
            )
    # Kiểm pattern compile được (chặn regex sai sớm)
    from date_format_rules import compile_pattern
    try:
        compile_pattern(body.pattern)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/date-format", response_model=list[DateFormatRuleOut])
def list_date_format_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    from models import DateFormatRule

    return (
        db.query(DateFormatRule)
        .order_by(DateFormatRule.priority.asc(), DateFormatRule.id.asc())
        .all()
    )


@router.post("/date-format", response_model=DateFormatRuleOut)
def create_date_format_rule(
    body: DateFormatRuleIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from date_format_rules import invalidate_date_format_cache
    from models import DateFormatRule

    _validate_date_format_rule(body)
    rule = DateFormatRule(**body.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    invalidate_date_format_cache()
    invalidate_classification_cache()
    return rule


@router.put("/date-format/{rule_id}", response_model=DateFormatRuleOut)
def update_date_format_rule(
    rule_id: int,
    body: DateFormatRuleIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from date_format_rules import invalidate_date_format_cache
    from models import DateFormatRule

    _validate_date_format_rule(body)
    rule = db.query(DateFormatRule).filter(DateFormatRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    invalidate_date_format_cache()
    invalidate_classification_cache()
    return rule


@router.delete("/date-format/{rule_id}")
def delete_date_format_rule(
    rule_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from date_format_rules import invalidate_date_format_cache
    from models import DateFormatRule

    rule = db.query(DateFormatRule).filter(DateFormatRule.id == rule_id).first()
    if not rule:
        raise HTTPException(404, "Rule không tồn tại")
    db.delete(rule)
    db.commit()
    invalidate_date_format_cache()
    invalidate_classification_cache()
    return {"deleted": rule_id}


@router.post("/date-format/seed-defaults")
def seed_date_format_defaults(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    from date_format_rules import seed_default_rules

    added = seed_default_rules(db)
    invalidate_classification_cache()
    return {"added": added, "message": f"Đã thêm {added} rule mặc định"}


class DateFormatTestIn(BaseModel):
    # Bump 2048 → 32768 để hỗ trợ lich_kh dài (vd 200 dates DD/MM/YYYY = ~2400 char).
    # Tour.lich_kh là Text (unlimited DB) — test endpoint không nên chặn use case thật.
    text: str = Field(min_length=1, max_length=32768)


@router.post("/date-format/test")
def test_date_format(
    body: DateFormatTestIn,
    _: User = Depends(require_admin),
):
    """Test input text → return matched rule + parsed dates. Không ghi DB."""
    from date_format_rules import match_text

    dates, output_type, rule_id = match_text(body.text)
    return {
        "matched_rule_id": str(rule_id) if rule_id is not None else None,
        "output_type": output_type,
        "dates": [d.isoformat() for d in dates],
        "count": len(dates),
        "input": body.text,
    }


class ClassifyMarketOrderIn(BaseModel):
    markets: list[str] = Field(default_factory=list)


@router.get("/classify/market-order")
def get_classify_market_order(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from classify_market_order import merged_market_order

    return {"markets": merged_market_order(db)}


@router.put("/classify/market-order")
def put_classify_market_order(
    body: ClassifyMarketOrderIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from classify_market_order import save_market_order
    from rules_job_store import invalidate_unmatched_cache

    markets = save_market_order(db, body.markets)
    _on_market_route_rules_changed(db)
    invalidate_unmatched_cache()
    return {"markets": markets, "message": "Đã lưu thứ tự thị trường (trên xuống = ưu tiên)"}


@router.get("/preview-keyword")
def preview_keyword_match(
    keywords: str = Query(..., min_length=1, max_length=512,
                          description="Một hoặc nhiều keyword cách nhau dấu phẩy — tất cả phải có trong tên tour (AND)"),
    limit: int = Query(20, ge=1, le=50),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Xem thử keyword sẽ match tour nào — dùng trước khi lưu rule."""
    from sqlalchemy import and_, or_, func
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    kws = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if not kws:
        return {"keywords": [], "tour_count": 0, "samples": []}

    q = db.query(Tour.id, Tour.ten_tour, Tour.thi_truong, Tour.tuyen_tour, Tour.cong_ty).filter(
        Tour.nguon.in_(tuple(DB_CANONICAL_NGUON))
    )
    for kw in kws:
        q = q.filter(
            or_(
                func.lower(Tour.ten_tour).contains(kw),
                func.lower(Tour.lich_trinh).contains(kw),
            )
        )
    total = q.count()
    samples = q.limit(limit).all()
    return {
        "keywords": kws,
        "tour_count": total,
        "samples": [
            {
                "id": r.id,
                "ten_tour": r.ten_tour or "",
                "thi_truong": r.thi_truong or "",
                "tuyen_tour": r.tuyen_tour or "",
                "cong_ty": r.cong_ty or "",
            }
            for r in samples
        ],
    }


@router.get("/route-stats")
def route_rule_stats(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Số tour đang được gán bởi mỗi rule tuyến (classification_rule_id)."""
    from sqlalchemy import func
    from models import Tour

    rows = (
        db.query(Tour.classification_rule_id, func.count(Tour.id).label("cnt"))
        .filter(Tour.classification_rule_id.isnot(None))
        .group_by(Tour.classification_rule_id)
        .all()
    )
    return {str(rule_id): cnt for rule_id, cnt in rows}


@router.get("/unmatched-summary")
def unmatched_summary(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Số lượng chưa khớp per scope — dùng cho badge trên tab."""
    from classification import collect_classify_gaps, collect_unmatched_values
    from rules_job_store import get_unmatched_cached

    def _load_all():
        # load_only cột cần — cold path nhanh hơn (xem _unmatched_tours_query)
        return collect_unmatched_values(_unmatched_tours_query(db), vtr_only=False)

    def _load_classify():
        return {"classify": collect_classify_gaps(db)}

    try:
        data = get_unmatched_cached(db, "all", _load_all)
        classify_data = get_unmatched_cached(db, "classify", _load_classify)
        return {
            "classify": len(classify_data.get("classify", [])),
            "company": len(data.get("cong_ty", [])),
            "departure": len(data.get("diem_kh", [])),
            "duration": len(data.get("thoi_gian", [])),
            "schedule": len(data.get("lich_kh", [])),
        }
    except Exception:
        return {"classify": 0, "company": 0, "departure": 0, "duration": 0, "schedule": 0}


@router.get("/stats-exclusions")
def list_stats_exclusions(_: User = Depends(require_admin)):
    """Pattern tên tour bị loại khỏi KPI / compare (FIT placeholder)."""
    from tour_stats_exclusions import all_exclusion_substrings

    return {
        "patterns": list(all_exclusion_substrings()),
        "note": "Tour khớp bất kỳ pattern → không tính thống kê; vẫn hiện trên grid.",
    }


@router.get("/unmatched")
def list_unmatched_rules(
    scope: str = Query(
        "company",
        pattern="^(market|route|classify|company|departure|duration|schedule|all)$",
    ),
    fresh: bool = Query(False, description="Bỏ cache — dùng ngay sau Gán/Áp dụng"),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Tour chưa khớp quy tắc — thị trường/tuyến: mỗi dòng một tên tour."""
    from classification import collect_unmatched_values
    from rules_job_store import get_unmatched_cached, invalidate_unmatched_cache

    if scope == "classify":
        from classification import collect_classify_gaps

        def _load_classify() -> dict:
            return {"classify": collect_classify_gaps(db)}

        if fresh:
            invalidate_unmatched_cache()
            data = _load_classify()
        else:
            data = get_unmatched_cached(db, "classify", _load_classify)
        return {"scope": scope, "items": data["classify"]}

    def _load() -> dict:
        # load_only cột cần — cold path nhanh hơn (xem _unmatched_tours_query)
        return collect_unmatched_values(_unmatched_tours_query(db), vtr_only=False)

    if fresh:
        invalidate_unmatched_cache()
        data = _load()
    else:
        data = get_unmatched_cached(db, "all", _load)
    if scope == "market":
        return {"scope": scope, "items": data["thi_truong"]}
    if scope == "route":
        return {"scope": scope, "items": data["tuyen_tour"]}
    if scope == "company":
        return {"scope": scope, "items": data["cong_ty"]}
    if scope == "departure":
        return {"scope": scope, "items": data["diem_kh"]}
    if scope == "duration":
        return {"scope": scope, "items": data["thoi_gian"]}
    if scope == "schedule":
        return {"scope": scope, "items": data["lich_kh"]}
    return {"scope": "all", **data}


@router.post("/assign-classification")
def assign_classification(
    body: AssignClassificationIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Gán một lần: thị trường + tuyến + keyword (tạo/cập nhật rule + áp dụng tour)."""
    from classification import merge_keyword_csv

    mk = body.thi_truong.strip()
    route = (body.tuyen_tour or mk).strip()
    route_kws = merge_keyword_csv("", body.route_keywords)
    if not mk or not route_kws:
        raise HTTPException(400, "Cần thị trường (nhóm) và keyword tuyến")
    if not route:
        raise HTTPException(400, "Cần tên tuyến tour")

    _add_route_rule_row(db, mk, route, route_kws)

    db.commit()
    _on_market_route_rules_changed(db)
    kws = [k.strip().lower() for k in route_kws.split(",") if k.strip()]
    tours = _auto_apply_tours(db, body.auto_apply, scope="all", keywords=kws)
    return {
        "message": f"Đã gán tuyến {route} ({mk}) — keyword: {route_kws}",
        "thi_truong": mk,
        "tuyen_tour": route,
        "tours_apply": tours,
    }


@router.post("/assign-classification/bulk")
def assign_classification_bulk(
    body: BulkAssignClassificationIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Gán nhiều dòng rule cùng lúc — một lần commit + một lần áp dụng tour."""
    from classification import merge_keyword_csv

    added = 0
    all_kws: list[str] = []
    for item in body.items:
        mk = item.thi_truong.strip()
        route = (item.tuyen_tour or mk).strip()
        route_kws = merge_keyword_csv("", item.route_keywords)
        if not mk or not route_kws or not route:
            raise HTTPException(400, "Mỗi dòng cần thị trường, tuyến và keyword tuyến")
        if _add_route_rule_row(db, mk, route, route_kws):
            added += 1
        all_kws.extend(k.strip().lower() for k in route_kws.split(",") if k.strip())

    db.commit()
    _on_market_route_rules_changed(db)
    tours = _auto_apply_tours(db, body.auto_apply, scope="all", keywords=list(dict.fromkeys(all_kws)))
    n = len(body.items)
    return {
        "message": f"Đã gán {n} rule tuyến ({added} dòng mới)",
        "count": n,
        "added": added,
        "tours_apply": tours,
    }


@router.post("/market/assign-keyword")
def assign_market_keyword(
    market: str = Query(..., min_length=1),
    keyword: str = Query(..., min_length=1),
    auto_apply: bool = Query(False),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Thêm 1 keyword thị trường + áp dụng lên tour (gom nhanh VD esim → Esim)."""
    rule = MarketKeywordRule(market=market.strip(), keyword=keyword.strip().lower())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    _on_market_route_rules_changed(db)
    tours = _auto_apply_tours(db, auto_apply, scope="market")
    return {
        "rule": rule,
        "message": f"Đã thêm keyword «{keyword}» → {market}",
        "tours_apply": tours,
    }
