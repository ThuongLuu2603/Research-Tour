"""Ghép cặp tour VTR ↔ thị trường."""
from __future__ import annotations

from compare_engine import (
    deduplicate_tours,
    is_vietravel,
    normalize_departure,
    normalize_route,
    parse_duration_days,
    segment_key,
)
from data_sources import MIN_VALID_PRICE
from departure_parser import parse_departure_frequency
from models import Tour


def _score_match(vtr: Tour, cand: Tour) -> float | None:
    v_days = parse_duration_days(vtr.thoi_gian, vtr.so_ngay)
    c_days = parse_duration_days(cand.thoi_gian, cand.so_ngay)
    if not v_days or not c_days or not vtr.gia or not cand.gia:
        return None

    # GATE CỨNG thị trường: phải CÙNG thị trường đã phân loại. Trước đây chỉ loại khi
    # CẢ HAI có market khác nhau → tour đối thủ THIẾU market lọt qua, ghép Canada với
    # Nhật/Cù Lao Chàm. Giờ: thiếu market 1 bên hoặc khác market → KHÔNG ghép.
    v_market = (vtr.thi_truong or "").strip()
    c_market = (cand.thi_truong or "").strip()
    if not v_market or not c_market or v_market != c_market:
        return None

    v_route = normalize_route(vtr.tuyen_tour)
    c_route = normalize_route(cand.tuyen_tour)
    if v_route and c_route:
        if v_route == c_route:
            route_sim = 1.0
        elif v_route in c_route or c_route in v_route:
            route_sim = 0.6
        else:
            return None  # khác TUYẾN trong cùng thị trường (vd Canada vs Brazil) → không ghép
    else:
        route_sim = 0.3  # thiếu tuyến 1 bên: điểm thấp (KHÔNG dùng 0.6 do bug chuỗi rỗng cũ)

    v_dep = normalize_departure(vtr.diem_kh)
    c_dep = normalize_departure(cand.diem_kh)
    dep_sim = 1.0 if v_dep == c_dep else 0.3

    day_diff = abs(v_days - c_days)
    day_sim = max(0, 1 - day_diff / max(v_days, 1))

    price_ratio = cand.gia / vtr.gia if vtr.gia else 1
    price_sim = max(0, 1 - abs(price_ratio - 1) * 2)

    return round(route_sim * 0.4 + dep_sim * 0.25 + day_sim * 0.2 + price_sim * 0.15, 3)


def find_matches(tours: list[Tour], vtr_tour_id: int, limit: int = 8) -> dict:
    # VTR tour = ĐÚNG tour được click (tra trên tập ĐẦY ĐỦ, KHÔNG dedup) → tránh
    # dedup chọn đại diện khác id → phân tích nhầm tour (bug: click Miền Tây ra Huế).
    by_id = {t.id: t for t in tours}
    vtr = by_id.get(vtr_tour_id)
    if not vtr or not is_vietravel(vtr.cong_ty):
        return {"found": False, "message": "Tour không phải Vietravel hoặc không tồn tại"}

    seg = segment_key(vtr)
    candidates = []
    for t in deduplicate_tours(tours):  # chỉ dedup pool ứng viên đối thủ
        if is_vietravel(t.cong_ty) or t.id == vtr.id:
            continue
        score = _score_match(vtr, t)
        if score is None or score < 0.35:
            continue
        freq = parse_departure_frequency(t.lich_kh)["monthly_estimate"]
        days = parse_duration_days(t.thoi_gian, t.so_ngay) or 1
        candidates.append({
            "tour_id": str(t.id),  # chuỗi để JS không làm tròn id INT8
            "cong_ty": t.cong_ty,
            "ten_tour": t.ten_tour,
            "gia": t.gia,
            "gia_raw": t.gia_raw,
            "price_day": round((t.gia or 0) / days, 0),
            "thi_truong": t.thi_truong,
            "tuyen_tour": t.tuyen_tour,
            "diem_kh": t.diem_kh,
            "thoi_gian": t.thoi_gian,
            "departures_monthly": round(freq, 1),
            "link_url": t.link_url,
            "match_score": score,
            "price_gap_pct": round((vtr.gia / t.gia - 1) * 100, 1) if t.gia else None,
        })

    candidates.sort(key=lambda x: (-x["match_score"], abs(x.get("price_gap_pct") or 999)))
    v_days = parse_duration_days(vtr.thoi_gian, vtr.so_ngay) or 1
    return {
        "found": True,
        "vtr_tour": {
            "id": str(vtr.id),
            "ten_tour": vtr.ten_tour,
            "gia": vtr.gia,
            "thi_truong": vtr.thi_truong,
            "tuyen_tour": vtr.tuyen_tour,
            "diem_kh": vtr.diem_kh,
            "thoi_gian": vtr.thoi_gian,
            "price_day": round((vtr.gia or 0) / v_days, 0),
            "segment_key": seg,
            "link_url": vtr.link_url,
        },
        "matches": candidates[:limit],
    }


def suggest_vtr_tours(tours: list[Tour], limit: int = 20) -> list[dict]:
    tours = deduplicate_tours(tours)
    vtr_tours = [t for t in tours if is_vietravel(t.cong_ty) and t.gia and t.gia >= MIN_VALID_PRICE]
    vtr_tours.sort(key=lambda t: t.updated_at or t.created_at, reverse=True)
    return [
        {
            # id dạng CHUỖI: CockroachDB id ~1.18e18 > Number.MAX_SAFE_INTEGER → nếu trả
            # số, JS làm tròn → click trỏ nhầm tour khác (Seoul → Nhật Bản).
            "id": str(t.id),
            "ten_tour": t.ten_tour,
            "thi_truong": t.thi_truong,
            "tuyen_tour": t.tuyen_tour,
            "diem_kh": t.diem_kh,
            "thoi_gian": t.thoi_gian,
            "so_ngay": t.so_ngay,
            "link_url": t.link_url,
            "gia": t.gia,
        }
        for t in vtr_tours[:limit]
    ]
