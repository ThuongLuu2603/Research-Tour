"""Phân khúc giá theo TB/ngày tour so với TB/ngày TT trên cùng Thị trường + Tuyến + Điểm KH."""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from sqlalchemy import bindparam, update
from sqlalchemy.orm import Session

from data_sources import MIN_VALID_PRICE
from models import Tour

# Ghi phân khúc theo LÔ NHỎ để tránh 1 transaction khổng lồ bị CockroachDB hủy
# (SerializationFailure/ABORT_SPAN). Mỗi lô là 1 transaction riêng + retry lỗi tạm thời.
_PHAN_KHUC_BATCH = 300

# Cache route_avg trong RAM 60s. Tránh build lại cho mỗi PATCH edit tour
# (build ~300-500ms, scan 7000+ tour). Invalidate khi sync/scrape lớn.
_ROUTE_AVG_TTL = 60.0
_route_avg_cache: dict[str, float] | None = None
_route_avg_cache_ts: float = 0.0
_route_avg_lock = threading.Lock()

# Snapshot route_avg trên DISK (persistent_cache) — chỉ rebuild khi data BIẾN
# ĐỘNG NHIỀU: count tour có giá lệch ≥ 2% so với lúc chụp, hoặc snapshot > 24h,
# hoặc sync/scrape lớn gọi invalidate_route_avg_cache() (xoá file → force rebuild).
# Single-tour edit / cache RAM hết TTL → dùng lại snapshot, KHÔNG full scan.
_ROUTE_AVG_SNAPSHOT_NS = "route_avg_snapshot"
_ROUTE_AVG_SNAPSHOT_TTL_H = 24
_ROUTE_AVG_COUNT_DRIFT = 0.02  # 2%


def _route_avg_db_fingerprint(db: Session) -> dict:
    """Fingerprint data nguồn của route_avg: count + max(updated_at) tour canonical
    có giá hợp lệ (cùng filter với build). 1 aggregate query — rẻ hơn full scan."""
    from sqlalchemy import func
    from data_sources import DB_CANONICAL_NGUON
    row = (
        db.query(func.count(Tour.id), func.max(Tour.updated_at))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .one()
    )
    return {
        "count": int(row[0] or 0),
        "max_updated_at": row[1].isoformat() if row[1] else None,
    }


def _save_route_avg_snapshot(db: Session, route_avg: dict[str, float]) -> None:
    """Lưu route_avg FULL (toàn DB) + fingerprint ra disk. Best-effort."""
    if not route_avg:
        return
    try:
        import persistent_cache
        persistent_cache.save_json(
            _ROUTE_AVG_SNAPSHOT_NS,
            {"fingerprint": _route_avg_db_fingerprint(db), "route_avg": route_avg},
            ttl_hours=_ROUTE_AVG_SNAPSHOT_TTL_H,
        )
    except Exception:  # noqa: BLE001
        pass


def _load_route_avg_snapshot_if_fresh(db: Session) -> dict[str, float] | None:
    """Load snapshot disk nếu data CHƯA biến động nhiều.

    Điều kiện dùng lại (không rebuild): count tour có giá lệch < 2% so với
    fingerprint lúc chụp VÀ snapshot < 24h (load_json tự check TTL).
    Lệch ≥ 2% / quá hạn / file bị invalidate xoá → None (caller rebuild)."""
    try:
        import persistent_cache
        snap = persistent_cache.load_json(
            _ROUTE_AVG_SNAPSHOT_NS, max_age_hours=_ROUTE_AVG_SNAPSHOT_TTL_H
        )
        if not isinstance(snap, dict):
            return None
        route_avg = snap.get("route_avg")
        fp = snap.get("fingerprint") or {}
        snap_count = int(fp.get("count") or 0)
        if not isinstance(route_avg, dict) or not route_avg or snap_count <= 0:
            return None
        cur_count = _route_avg_db_fingerprint(db)["count"]
        drift = abs(cur_count - snap_count) / max(snap_count, 1)
        if drift >= _ROUTE_AVG_COUNT_DRIFT:
            return None  # biến động nhiều → rebuild
        return {str(k): float(v) for k, v in route_avg.items()}
    except Exception:  # noqa: BLE001
        return None


def _set_route_avg_ram(route_avg: dict[str, float]) -> None:
    global _route_avg_cache, _route_avg_cache_ts
    with _route_avg_lock:
        _route_avg_cache = route_avg
        _route_avg_cache_ts = time.time()


def _get_route_avg_ram_warm() -> dict[str, float] | None:
    now = time.time()
    with _route_avg_lock:
        if _route_avg_cache is not None and (now - _route_avg_cache_ts) < _ROUTE_AVG_TTL:
            return _route_avg_cache
    return None


def get_cached_route_avg(db: Session) -> dict[str, float]:
    """Lấy route_avg: RAM warm → snapshot disk (nếu data chưa biến động nhiều)
    → rebuild full + save snapshot. Tránh full scan khi data không đổi đáng kể."""
    warm = _get_route_avg_ram_warm()
    if warm is not None:
        return warm
    # RAM cold → thử snapshot disk: count lệch < 2% & < 24h → dùng luôn, KHÔNG rebuild.
    snap = _load_route_avg_snapshot_if_fresh(db)
    if snap is not None:
        _set_route_avg_ram(snap)
        return snap
    # Biến động nhiều / không có snapshot → build full (ngoài lock) + save snapshot mới.
    from sqlalchemy.orm import load_only
    from data_sources import DB_CANONICAL_NGUON
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.lich_kh, Tour.nguon)
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .all()
    )
    fresh = build_route_market_avg_price_day(all_priced)
    _set_route_avg_ram(fresh)
    _save_route_avg_snapshot(db, fresh)
    return fresh


def invalidate_route_avg_cache() -> None:
    """Xoá RAM cache + snapshot disk route_avg — gọi sau sync lớn / scrape mới /
    bulk PATCH (semantics giữ nguyên: biến động lớn → force rebuild lần đọc sau)."""
    global _route_avg_cache, _route_avg_cache_ts
    with _route_avg_lock:
        _route_avg_cache = None
        _route_avg_cache_ts = 0.0
    try:
        import persistent_cache
        persistent_cache.delete_json(_ROUTE_AVG_SNAPSHOT_NS)
    except Exception:  # noqa: BLE001
        pass


def _build_market_scoped_route_avg(db: Session, thi_truong: str) -> dict[str, float]:
    """Build route_avg CHỈ cho 1 thị trường — nhanh hơn full scan rất nhiều.

    Chính xác cho bucket của tour vì bucket_key = market | route | departure;
    mọi tour cùng bucket đều cùng market → filter market không làm sai giá TB.
    7000 tour → vài trăm tour cùng market → sub-second thay vì 20-30s.
    """
    from sqlalchemy.orm import load_only
    from data_sources import DB_CANONICAL_NGUON
    _COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
             Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.lich_kh, Tour.nguon)
    candidates = (
        db.query(Tour)
        .options(load_only(*_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .filter(Tour.thi_truong == (thi_truong or ""))
        .all()
    )
    return build_route_market_avg_price_day(candidates)


def recompute_phan_khuc_for_single_tour_sync(db: Session, tour: Tour) -> str:
    """Tính lại phân khúc cho 1 tour ĐỒNG BỘ — KHÔNG bao giờ full scan 7000 tour.

    Chiến lược:
      1. Cache route_avg toàn DB còn warm (TTL 60s) → dùng ngay (instant).
      2. RAM cold → snapshot disk (data chưa biến động ≥ 2% & < 24h) → dùng luôn.
      3. Không có snapshot hợp lệ → build route_avg CHỈ cho thị trường của tour
         (market-scoped, sub-second). KHÔNG BAO GIỜ full scan → tránh block 20-30s.
    Skip nếu tour là Vietravel (phân khúc VTR = Dòng tour, không tính lại)."""
    if (tour.nguon or "") == "Vietravel":
        return tour.phan_khuc or ""

    # Fast path: full cache còn warm → dùng luôn (rẻ nhất).
    route_avg = _get_route_avg_ram_warm()
    if route_avg is None:
        # Snapshot disk còn hợp lệ → dùng (instant, không scan).
        route_avg = _load_route_avg_snapshot_if_fresh(db)
        if route_avg is not None:
            _set_route_avg_ram(route_avg)
    if route_avg is None:
        # Cold: market-scoped build — nhanh, chính xác cho bucket, KHÔNG full scan.
        # KHÔNG save snapshot (partial — chỉ 1 thị trường).
        route_avg = _build_market_scoped_route_avg(db, tour.thi_truong or "")

    label = phan_khuc_relative_for_tour(tour, route_avg)
    if tour.phan_khuc != label:
        tour.phan_khuc = label[:64]
        db.commit()
    return tour.phan_khuc or ""


def _beat(progress, msg: str) -> None:
    """Gửi nhịp tiến độ (cập nhật heartbeat job) — bỏ qua nếu lỗi."""
    if not progress:
        return
    try:
        progress(msg)
    except Exception:  # noqa: BLE001
        pass


def _apply_phan_khuc_updates(db: Session, updates: list[dict], cancel_check=None, progress=None) -> int:
    """updates = [{'b_id': id, 'b_pk': label}, ...] → UPDATE theo lô nhỏ, commit + retry từng lô.
    Kiểm tra cancel giữa mỗi lô → dừng sớm khi người dùng bấm Dừng.
    Gọi ``progress(msg)`` mỗi lô để giữ heartbeat (job không bị coi là treo)."""
    if not updates:
        return 0
    from db_retry import run_with_retry
    from job_cancel import raise_if_cancelled

    # Dùng CORE update trên Tour.__table__ (KHÔNG qua ORM entity). SQLAlchemy 2.0
    # diễn giải update(Tour) + executemany thành "ORM Bulk UPDATE by Primary Key"
    # (đòi cột 'id' trong mỗi dict) HOẶC chặn vì persistent objects trong session →
    # mọi recompute phân khúc CRASH → toàn bộ tour rỗng phân khúc. Core update bằng
    # WHERE + bindparam + executemany chạy chuẩn, không bị 2 lỗi đó.
    _tbl = Tour.__table__
    stmt = (
        update(_tbl)
        .where(_tbl.c.id == bindparam("b_id"))
        .values(phan_khuc=bindparam("b_pk"))
    )
    total = len(updates)
    for i in range(0, total, _PHAN_KHUC_BATCH):
        raise_if_cancelled(cancel_check)
        batch = updates[i:i + _PHAN_KHUC_BATCH]
        _beat(progress, f"Đang ghi phân khúc giá: {min(i + _PHAN_KHUC_BATCH, total):,}/{total:,}")

        def _do(b=batch):
            db.execute(stmt, b)
            db.commit()

        run_with_retry(_do, db=db, label="phan-khuc-batch")
    return total

# Ngưỡng so với TB/ngày thị trường (cùng nhóm segment)
LUXURY_ABOVE_MARKET = 1.30
STANDARD_BELOW_MARKET = 0.70


def bucket_key_for_tour(t: Tour) -> str | None:
    """Cùng khóa nhóm với So sánh VTR: Thị trường | Tuyến | Điểm khởi hành."""
    from compare_engine import make_segment_key, normalize_departure, route_for_segment

    route = route_for_segment(t)
    if not route:
        return None
    market = (t.thi_truong or "").strip() or "Khác"
    depart = normalize_departure(t.diem_kh)
    return make_segment_key(market, route, depart)


def tour_price_per_day(gia: float | None, thoi_gian: str, so_ngay: float | None) -> float | None:
    from classification import resolve_duration_days

    days, _ = resolve_duration_days(thoi_gian or "", so_ngay)
    # gia < MIN_VALID_PRICE = giá placeholder/lỗi (Liên hệ/0đ/test) — đã bị loại
    # khỏi route_avg nên cũng KHÔNG xếp hạng tương đối → "Chưa có giá" (caller),
    # thay vì để phan_khuc rỗng vĩnh viễn (trước đây bị skip khỏi mọi recompute).
    if not gia or float(gia) < MIN_VALID_PRICE or not days or days <= 0:
        return None
    pd = float(gia) / float(days)
    if pd <= 0 or pd > 50_000_000:
        return None
    return pd


def _departure_weight_for_tour(t: Tour) -> float:
    """Số ngày khởi hành (đoàn) của tour = trọng số. Khớp So Sánh VTR (_departure_weight):
    ưu tiên số ngày KH cụ thể, nếu không có thì ước lượng/tháng, tối thiểu 1."""
    try:
        from departure_parser import parse_departure_frequency

        info = parse_departure_frequency(t.lich_kh or "")
        explicit = info.get("explicit_dates") or 0
        if explicit > 0:
            return float(explicit)
        return max(float(info.get("monthly_estimate") or 1.0), 1.0)
    except Exception:  # noqa: BLE001
        return 1.0


def build_route_market_avg_price_day(tours: list[Tour]) -> dict[str, float]:
    """Giá TB/ngày TT của tuyến = Σ(giá tour × số ngày KH) / Σ(số ngày tour × số ngày KH).

    Đúng công thức So Sánh VTR (_route_avg_price_per_day): TRỌNG SỐ theo số đoàn khởi hành,
    KHÔNG phải trung bình cộng đơn giản. Chỉ tính tour đối thủ (không tab Vietravel)."""
    from classification import resolve_duration_days
    from tour_sources import is_vietravel_tab

    num: dict[str, float] = defaultdict(float)  # Σ(giá × đoàn)
    den: dict[str, float] = defaultdict(float)  # Σ(ngày × đoàn)
    for t in tours:
        if is_vietravel_tab(t):
            continue
        days, _ = resolve_duration_days(t.thoi_gian or "", t.so_ngay)
        if not t.gia or not days or days <= 0:
            continue
        key = bucket_key_for_tour(t)
        if not key:
            continue
        w = _departure_weight_for_tour(t)
        num[key] += float(t.gia) * w
        den[key] += float(days) * w
    out: dict[str, float] = {}
    for k in num:
        if den[k] > 0:
            avg = round(num[k] / den[k], 0)
            if 0 < avg <= 50_000_000:
                out[k] = avg
    return out


def phan_khuc_relative_for_tour(t: Tour, route_avg: dict[str, float]) -> str:
    pd = tour_price_per_day(t.gia, t.thoi_gian, t.so_ngay)
    if pd is None:
        return "Chưa có giá"
    key = bucket_key_for_tour(t)
    mkt = route_avg.get(key) if key else None
    if not mkt:
        return _phan_khuc_absolute_fallback(t.gia)
    ratio = pd / mkt
    if ratio >= LUXURY_ABOVE_MARKET:
        return "Luxury"
    if ratio <= STANDARD_BELOW_MARKET:
        return "Standard"
    return "Premium"


def _phan_khuc_absolute_fallback(gia: float | None) -> str:
    if not gia:
        return "Chưa có giá"
    if gia < 2_000_000:
        return "Standard"
    if gia < 5_000_000:
        return "Standard"
    if gia < 15_000_000:
        return "Premium"
    return "Luxury"


def _label_unpriced_tours(db: Session, only_missing: bool = True, cancel_check=None, progress=None) -> int:
    """Gán "Chưa có giá" cho tour canonical KHÔNG có giá hợp lệ (gia NULL hoặc
    < MIN_VALID_PRICE) — các tour này bị filter khỏi mọi query recompute
    (gia >= MIN_VALID_PRICE) nên trước đây phan_khuc="" tồn tại VĨNH VIỄN.

    only_missing=True: chỉ fill tour đang rỗng/NULL (an toàn, dùng cho safety net).
    only_missing=False: chuẩn hoá cả nhãn cũ stale (vd "Standard" từ lúc còn giá)
    → "Chưa có giá" (dùng trong recompute_all).
    Skip Vietravel (phân khúc VTR = Dòng tour, chờ dong_tour từ scrape)."""
    from data_sources import DB_CANONICAL_NGUON
    from sqlalchemy import or_

    q = (
        db.query(Tour.id)
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.nguon != "Vietravel")
        .filter(or_(Tour.gia.is_(None), Tour.gia < MIN_VALID_PRICE))
    )
    if only_missing:
        q = q.filter(or_(Tour.phan_khuc.is_(None), Tour.phan_khuc == ""))
    else:
        q = q.filter(or_(Tour.phan_khuc.is_(None), Tour.phan_khuc != "Chưa có giá"))
    ids = [r[0] for r in q.all()]
    if not ids:
        return 0
    updates = [{"b_id": i, "b_pk": "Chưa có giá"} for i in ids]
    return _apply_phan_khuc_updates(db, updates, cancel_check, progress)


def recompute_all_phan_khuc(db: Session, cancel_check=None, progress=None) -> dict:
    from sqlalchemy.orm import load_only
    from data_sources import DB_CANONICAL_NGUON

    _beat(progress, "Đang tính phân khúc giá (toàn bộ)…")
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    tours = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(tours)
    _set_route_avg_ram(route_avg)
    _save_route_avg_snapshot(db, route_avg)
    updates = []
    for t in tours:
        if (t.nguon or "") == "Vietravel":
            continue  # phân khúc VTR = Dòng tour → KHÔNG tính lại, không ghi đè
        label = phan_khuc_relative_for_tour(t, route_avg)
        if t.phan_khuc != label:
            updates.append({"b_id": t.id, "b_pk": label[:64]})
    updated = _apply_phan_khuc_updates(db, updates, cancel_check, progress)
    # Tour KHÔNG có giá hợp lệ (gia NULL / < MIN_VALID_PRICE) bị filter khỏi query
    # trên → chuẩn hoá nhãn "Chưa có giá" để recompute-all không bỏ sót tour rỗng.
    unpriced = _label_unpriced_tours(db, only_missing=False, cancel_check=cancel_check, progress=progress)
    return {"updated": updated + unpriced, "unpriced_labeled": unpriced, "route_buckets": len(route_avg)}


def recompute_phan_khuc_for_tour_ids(db: Session, tour_ids: list[int], cancel_check=None, progress=None) -> dict:
    """Tính lại phân khúc cho danh sách tour (vd. sau scrape chỉ tour mới/cập nhật)."""
    from data_sources import DB_CANONICAL_NGUON
    from job_cancel import raise_if_cancelled

    ids = [int(i) for i in tour_ids if i]
    if not ids:
        return {"updated": 0, "tours": 0}

    from sqlalchemy.orm import load_only
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    _beat(progress, "Đang tính phân khúc giá (tour thay đổi)…")
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(all_priced)
    _set_route_avg_ram(route_avg)
    _save_route_avg_snapshot(db, route_avg)
    # Đọc tour mục tiêu theo LÔ — tránh IN (8000+ id) khổng lồ làm CockroachDB treo/chậm.
    tours = []
    for i in range(0, len(ids), 1000):
        raise_if_cancelled(cancel_check)
        chunk = ids[i:i + 1000]
        tours.extend(
            db.query(Tour).options(load_only(*_PRICE_COLS)).filter(Tour.id.in_(chunk)).all()
        )
    updates = []
    for t in tours:
        if (t.nguon or "") == "Vietravel":
            continue  # phân khúc VTR = Dòng tour → KHÔNG tính lại, không ghi đè
        label = phan_khuc_relative_for_tour(t, route_avg)
        if t.phan_khuc != label:
            updates.append({"b_id": t.id, "b_pk": label[:64]})
    updated = _apply_phan_khuc_updates(db, updates, cancel_check, progress)
    return {"updated": updated, "tours": len(tours), "route_buckets": len(route_avg)}


def recompute_segments_for_sync(
    db: Session, affected_tour_ids: set[int] | list[int], cancel_check=None, progress=None
) -> dict:
    """Phân khúc cho tour mới (thiếu nhãn) + tour vừa thay đổi.
    Sync LỚN (đổi gần hết) → quét toàn bộ 1 lần (rẻ hơn missing + IN khổng lồ, tránh treo)."""
    affected = list(affected_tour_ids)
    if len(affected) > 1500:
        res = recompute_all_phan_khuc(db, cancel_check, progress)
        return {
            "missing_filled": 0,
            "targeted_updated": res.get("updated", 0),
            "targeted_tours": len(affected),
            "route_buckets": res.get("route_buckets", 0),
        }
    missing = recompute_missing_phan_khuc(db, cancel_check, progress)
    targeted = recompute_phan_khuc_for_tour_ids(db, affected, cancel_check, progress)
    return {
        "missing_filled": missing,
        "targeted_updated": targeted.get("updated", 0),
        "targeted_tours": targeted.get("tours", 0),
        "route_buckets": targeted.get("route_buckets", 0),
    }


def recompute_missing_phan_khuc(db: Session, cancel_check=None, progress=None) -> int:
    """Tính phân khúc cho tour có giá nhưng chưa có nhãn (vd. Vietravel mới scrape)."""
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour
    from sqlalchemy import or_

    from sqlalchemy.orm import load_only
    _PRICE_COLS = (Tour.id, Tour.thi_truong, Tour.tuyen_tour, Tour.diem_kh,
                   Tour.gia, Tour.thoi_gian, Tour.so_ngay, Tour.phan_khuc, Tour.nguon)
    _beat(progress, "Đang tính phân khúc giá (tour thiếu nhãn)…")
    # Safety net cho tour KHÔNG có giá hợp lệ (gia NULL / < MIN_VALID_PRICE):
    # bị filter khỏi query bên dưới → trước đây phan_khuc="" rỗng VĨNH VIỄN.
    # Giờ gán "Chưa có giá" để mọi tour canonical đều có nhãn khác rỗng.
    unpriced_filled = _label_unpriced_tours(db, only_missing=True, cancel_check=cancel_check, progress=progress)
    tours = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .filter(or_(Tour.phan_khuc.is_(None), Tour.phan_khuc == "", Tour.phan_khuc == "Chưa có giá"))
        .all()
    )
    if not tours:
        return unpriced_filled
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(all_priced)
    _set_route_avg_ram(route_avg)
    _save_route_avg_snapshot(db, route_avg)
    updates = []
    for t in tours:
        if (t.nguon or "") == "Vietravel":
            continue  # phân khúc VTR = Dòng tour → KHÔNG tính lại, không ghi đè
        label = phan_khuc_relative_for_tour(t, route_avg)
        if label and t.phan_khuc != label:
            updates.append({"b_id": t.id, "b_pk": label[:64]})
    return unpriced_filled + _apply_phan_khuc_updates(db, updates, cancel_check, progress)
