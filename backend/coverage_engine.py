"""Coverage map — phủ sóng VTR vs thị trường.

NGUYÊN TẮC: CHỈ tính tour CÓ lịch khởi hành (parse được ngày qua rule). Tour không
có ngày / không khớp định dạng → KHÔNG đếm (không tính giá/tần suất/phủ sóng).
"""
from __future__ import annotations

from collections import defaultdict

from compare_engine import deduplicate_tours, is_vietravel, parse_duration_days
from departure_parser import parse_departure_frequency
from models import Tour


def _tour_freq(t: Tour) -> float:
    """Số đoàn KH/tháng từ lich_kh (0 = không có ngày / không khớp định dạng)."""
    return float(parse_departure_frequency(t.lich_kh or "").get("monthly_estimate") or 0.0)


def build_coverage_summary(tours: list[Tour]) -> dict:
    tours = deduplicate_tours(tours)
    cells: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "vtr": 0, "mkt": 0, "companies": set(), "mkt_freq": 0.0, "pd_pairs": [],
    })

    for t in tours:
        freq = _tour_freq(t)
        if freq <= 0:
            continue  # KHÔNG có lịch KH → bỏ (không tính giá/tần suất/phủ sóng)
        market = (t.thi_truong or "").strip() or "Khác"
        route = (t.tuyen_tour or "").strip() or market
        c = cells[(market, route)]
        if is_vietravel(t.cong_ty):
            c["vtr"] += 1
        else:
            c["mkt"] += 1
            if t.cong_ty:
                c["companies"].add(t.cong_ty)
            c["mkt_freq"] += freq
            days = parse_duration_days(t.thoi_gian, t.so_ngay)
            if t.gia and days and days > 0:
                pd_val = float(t.gia) / days
                if pd_val > 0:
                    c["pd_pairs"].append((pd_val, freq))

    matrix = []
    gaps = []
    both = vtr_only = market_only = 0

    for (market, route), d in sorted(cells.items(), key=lambda x: -(x[1]["vtr"] + x[1]["mkt"])):
        vt, mt = d["vtr"], d["mkt"]
        companies = len(d["companies"])
        if vt > 0 and mt > 0:
            status = "both"
            both += 1
        elif vt > 0:
            status = "vtr_only"
            vtr_only += 1
        else:
            status = "market_only"
            market_only += 1
            if mt >= 3:
                freq_total = round(d["mkt_freq"], 1)
                pairs = d["pd_pairs"]
                wsum = sum(w for _, w in pairs)
                price_day = round(sum(p * w for p, w in pairs) / wsum, 0) if wsum > 0 else None
                gaps.append({
                    "thi_truong": market,
                    "tuyen_tour": route,
                    "market_tours": mt,
                    "companies": companies,
                    "market_departures_monthly": freq_total,
                    "market_price_day": price_day,
                    # Score cơ hội = nhu cầu (đoàn TT/tháng) × số đối thủ (thị trường đã được kiểm chứng).
                    "opportunity_score": round(freq_total * companies, 1),
                })

        matrix.append({
            "thi_truong": market,
            "tuyen_tour": route,
            "vtr_tours": vt,
            "market_tours": mt,
            "status": status,
            "competitor_count": companies,
        })

    gaps.sort(key=lambda x: -(x["opportunity_score"] or 0))
    return {
        "summary": {
            "both": both, "vtr_only": vtr_only, "market_only": market_only,
            "gap_opportunities": len(gaps),
            "total_segments": len(matrix),
        },
        "matrix": matrix,
        "gaps": gaps,
    }


def build_coverage_for_api(tours: list[Tour]) -> dict:
    return build_coverage_summary(tours)
