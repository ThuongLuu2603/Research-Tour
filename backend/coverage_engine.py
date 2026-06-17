"""Coverage map — phủ sóng VTR vs thị trường."""
from __future__ import annotations

from collections import defaultdict

from compare_engine import deduplicate_tours, is_vietravel
from models import Tour


def build_coverage_summary(tours: list[Tour]) -> dict:
    tours = deduplicate_tours(tours)
    cells: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "vtr_tours": 0, "market_tours": 0, "vtr_segments": set(), "market_companies": set(),
    })

    for t in tours:
        market = (t.thi_truong or "").strip() or "Khác"
        route = (t.tuyen_tour or "").strip() or market
        key = (market, route)
        if is_vietravel(t.cong_ty):
            cells[key]["vtr_tours"] += 1
        else:
            cells[key]["market_tours"] += 1
            if t.cong_ty:
                cells[key]["market_companies"].add(t.cong_ty)

    matrix = []
    gaps = []
    both = vtr_only = market_only = 0

    for (market, route), data in sorted(cells.items(), key=lambda x: -(x[1]["vtr_tours"] + x[1]["market_tours"])):
        vt, mt = data["vtr_tours"], data["market_tours"]
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
                gaps.append({
                    "thi_truong": market,
                    "tuyen_tour": route,
                    "market_tours": mt,
                    "companies": len(data["market_companies"]),
                })

        matrix.append({
            "thi_truong": market,
            "tuyen_tour": route,
            "vtr_tours": vt,
            "market_tours": mt,
            "status": status,
            "competitor_count": len(data["market_companies"]),
        })

    gaps.sort(key=lambda x: -x["market_tours"])
    return {
        "summary": {
            "both": both, "vtr_only": vtr_only, "market_only": market_only,
            "gap_opportunities": len(gaps),
            "total_segments": len(matrix),  # tổng (thị trường, tuyến) = both+vtr_only+market_only
        },
        "matrix": matrix,        # FULL (không giới hạn 80) — FE tự lọc/phân trang
        "gaps": gaps,            # FULL
    }


def build_coverage_for_api(tours: list[Tour]) -> dict:
    return build_coverage_summary(tours)
