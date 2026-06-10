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


def get_cached_route_avg(db: Session) -> dict[str, float]:
    """Lấy route_avg từ RAM cache (TTL 60s) hoặc build lại."""
    global _route_avg_cache, _route_avg_cache_ts
    now = time.time()
    with _route_avg_lock:
        if _route_avg_cache is not None and (now - _route_avg_cache_ts) < _ROUTE_AVG_TTL:
            return _route_avg_cache
    # Miss → build (ngoài lock để không block reader)
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
    with _route_avg_lock:
        _route_avg_cache = fresh
        _route_avg_cache_ts = time.time()
    return fresh


def invalidate_route_avg_cache() -> None:
    """Xoá RAM cache route_avg — gọi sau sync lớn / scrape mới / bulk PATCH."""
    global _route_avg_cache, _route_avg_cache_ts
    with _route_avg_lock:
        _route_avg_cache = None
        _route_avg_cache_ts = 0.0


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
      2. Cache cold → build route_avg CHỈ cho thị trường của tour (market-scoped,
         sub-second, chính xác cho bucket này). KHÔNG full scan → tránh block 20-30s.
    Skip nếu tour là Vietravel (phân khúc VTR = Dòng tour, không tính lại)."""
    if (tour.nguon or "") == "Vietravel":
        return tour.phan_khuc or ""

    # Fast path: full cache còn warm → dùng luôn (rẻ nhất).
    now = time.time()
    with _route_avg_lock:
        warm = (
            _route_avg_cache
            if (_route_avg_cache is not None and (now - _route_avg_cache_ts) < _ROUTE_AVG_TTL)
            else None
        )
    if warm is not None:
        route_avg = warm
    else:
        # Cold: market-scoped build — nhanh, chính xác, KHÔNG full scan.
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

    stmt = (
        update(Tour)
        .where(Tour.id == bindparam("b_id"))
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
    if not gia or not days or days <= 0:
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
    updates = []
    for t in tours:
        if (t.nguon or "") == "Vietravel":
            continue  # phân khúc VTR = Dòng tour → KHÔNG tính lại, không ghi đè
        label = phan_khuc_relative_for_tour(t, route_avg)
        if t.phan_khuc != label:
            updates.append({"b_id": t.id, "b_pk": label[:64]})
    updated = _apply_phan_khuc_updates(db, updates, cancel_check, progress)
    return {"updated": updated, "route_buckets": len(route_avg)}


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
    tours = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .filter(or_(Tour.phan_khuc.is_(None), Tour.phan_khuc == "", Tour.phan_khuc == "Chưa có giá"))
        .all()
    )
    if not tours:
        return 0
    all_priced = (
        db.query(Tour)
        .options(load_only(*_PRICE_COLS))
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
        .all()
    )
    route_avg = build_route_market_avg_price_day(all_priced)
    updates = []
    for t in tours:
        if (t.nguon or "") == "Vietravel":
            continue  # phân khúc VTR = Dòng tour → KHÔNG tính lại, không ghi đè
        label = phan_khuc_relative_for_tour(t, route_avg)
        if label and t.phan_khuc != label:
            updates.append({"b_id": t.id, "b_pk": label[:64]})
    return _apply_phan_khuc_updates(db, updates, cancel_check, progress)
