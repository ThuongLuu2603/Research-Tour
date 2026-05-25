"""Data quality metrics."""
from __future__ import annotations

from sqlalchemy.orm import Session

from compare_engine import deduplicate_tours, is_vietravel
from models import ScrapeJob, Tour


def compute_data_quality(db: Session, tours: list[Tour] | None = None) -> dict:
    if tours is None:
        tours = db.query(Tour).all()
    tours = deduplicate_tours(tours)
    total = len(tours) or 1

    unclassified = sum(
        1 for t in tours
        if not (t.thi_truong or "").strip() or (t.thi_truong or "").strip() in ("Khác",)
        or not (t.tuyen_tour or "").strip()
        or (t.tuyen_tour or "").strip() == (t.thi_truong or "").strip()
    )
    no_price = sum(1 for t in tours if not t.gia or t.gia <= 0)
    no_departure = sum(1 for t in tours if not (t.diem_kh or "").strip())
    flagged = sum(1 for t in tours if t.flagged)
    vtr = sum(1 for t in tours if is_vietravel(t.cong_ty))

    last_jobs = (
        db.query(ScrapeJob)
        .filter(ScrapeJob.status == "success")
        .order_by(ScrapeJob.finished_at.desc())
        .limit(5)
        .all()
    )

    return {
        "total_tours": len(tours),
        "vtr_tours": vtr,
        "unclassified_count": unclassified,
        "unclassified_pct": round(unclassified / total * 100, 1),
        "no_price_count": no_price,
        "no_departure_count": no_departure,
        "flagged_count": flagged,
        "classified_pct": round((total - unclassified) / total * 100, 1),
        "last_scrapes": [
            {
                "scraper": j.scraper_name,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "tours_total": j.tours_total,
            }
            for j in last_jobs
        ],
    }
