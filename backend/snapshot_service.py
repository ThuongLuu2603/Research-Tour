"""Snapshot hàng ngày — nền tảng trend, insight, báo cáo."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from compare_engine import build_segment_stats, deduplicate_tours, is_vietravel
from data_sources import MIN_VALID_PRICE
from models import DailySnapshot, IntelAlert, SegmentSnapshot, Tour
from tour_sources import apply_market_compare_source_filter, filter_tours_for_market_compare


def _today() -> date:
    return date.today()


def capture_daily_snapshot(db: Session, tours: list[Tour] | None = None) -> DailySnapshot:
    if tours is None:
        # KHÔNG load_only: tránh N+1 khi build_segment_stats access phan_khuc,
        # dong_tour, festival_slug, etc. Postgres self-host không tốn egress.
        tours = filter_tours_for_market_compare(
            apply_market_compare_source_filter(
                db.query(Tour)
                .filter(Tour.gia != None, Tour.gia >= MIN_VALID_PRICE)  # noqa: E711
            ).all()
        )

    tours = deduplicate_tours(tours)
    snap_date = _today()

    existing = db.query(DailySnapshot).filter(DailySnapshot.snapshot_date == snap_date).first()
    if existing:
        db.delete(existing)
        db.query(SegmentSnapshot).filter(SegmentSnapshot.snapshot_date == snap_date).delete()
        db.commit()

    segments = build_segment_stats(tours, dedup=False)
    gaps, cheaper, expensive, similar = [], 0, 0, 0
    freq_lead, freq_lag = 0, 0
    vtr_freq_total = 0.0

    for s in segments:
        g = s.gap_pct
        if g is not None:
            gaps.append(g)
            if g <= -5:
                cheaper += 1
            elif g >= 5:
                expensive += 1
            else:
                similar += 1
        fg = s.freq_gap_vs_avg_pct  # dẫn/kém so đối thủ TB (cùng cấp độ), khớp Home/live
        if fg is not None:
            if fg >= 20:
                freq_lead += 1
            elif fg <= -20:
                freq_lag += 1
        vtr_freq_total += s.vtr_freq_monthly

        db.add(SegmentSnapshot(
            snapshot_date=snap_date,
            segment_key=s.key,
            thi_truong=s.thi_truong,
            tuyen_tour=s.tuyen_tour,
            diem_kh=s.diem_kh,
            so_ngay=s.so_ngay,
            gap_pct=s.gap_pct,
            freq_gap_pct=s.freq_gap_pct,
            vtr_avg_price=s.vtr_avg_price,
            comparison_price=s.comparison_price,
            vtr_avg_departures=s.vtr_avg_departures_per_month,
            market_avg_departures=s.market_freq_avg_per_company,
            vtr_tour_count=len(s.vtr_entries),
            market_tour_count=len(s.market_entries),
        ))

    unclassified = sum(
        1 for t in tours
        if not (t.thi_truong or "").strip() or t.thi_truong in ("Khác", "")
        or not (t.tuyen_tour or "").strip() or t.tuyen_tour == t.thi_truong
    )
    vtr_count = sum(1 for t in tours if is_vietravel(t.cong_ty))

    daily = DailySnapshot(
        snapshot_date=snap_date,
        total_tours=len(tours),
        vtr_tours=vtr_count,
        segment_count=len(segments),
        cheaper_segments=cheaper,
        expensive_segments=expensive,
        similar_segments=similar,
        avg_gap_pct=round(sum(gaps) / len(gaps), 1) if gaps else None,
        freq_leading_segments=freq_lead,
        freq_lagging_segments=freq_lag,
        vtr_departures_monthly=round(vtr_freq_total, 1),
        unclassified_tours=unclassified,
        flagged_tours=sum(1 for t in tours if t.flagged),
        created_at=datetime.utcnow(),
    )
    db.add(daily)
    db.commit()
    db.refresh(daily)

    from insight_engine import generate_alerts, generate_insights
    insights = generate_insights(db, tours, daily)
    daily.insights_json = insights
    generate_alerts(db, tours, daily, insights)

    from market_lab_engine import capture_route_daily_metrics, generate_route_alerts
    from market_lab_cache import get_cached_routes

    capture_route_daily_metrics(db, tours)
    generate_route_alerts(db, get_cached_routes(db))

    db.commit()
    db.refresh(daily)

    # Dựng lại & LƯU báo cáo BGĐ theo dữ liệu mới (snapshot ngày / Làm mới tự chạy) →
    # ghi đè bản đã chỉnh sửa tay. Best-effort, không làm hỏng snapshot nếu lỗi.
    try:
        from report_builder import build_report_html
        from persistent_cache import save_text

        save_text("report_html_saved", build_report_html(db, "daily"), ttl_hours=24 * 30)
    except Exception:  # noqa: BLE001
        pass

    return daily


def get_trend(db: Session, days: int = 30) -> list[dict]:
    since = _today() - timedelta(days=days)
    rows = (
        db.query(DailySnapshot)
        .filter(DailySnapshot.snapshot_date >= since)
        .order_by(DailySnapshot.snapshot_date)
        .all()
    )
    return [
        {
            "date": r.snapshot_date.isoformat(),
            "avg_gap_pct": r.avg_gap_pct,
            "cheaper_segments": r.cheaper_segments,
            "expensive_segments": r.expensive_segments,
            "segment_count": r.segment_count,
            "unclassified_tours": r.unclassified_tours,
        }
        for r in rows
    ]


def delta_vs_previous(db: Session) -> dict | None:
    rows = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).limit(2).all()
    if len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]

    def d(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 1)

    return {
        "current_date": cur.snapshot_date.isoformat(),
        "previous_date": prev.snapshot_date.isoformat(),
        "avg_gap_pct_delta": d(cur.avg_gap_pct, prev.avg_gap_pct),
        "cheaper_delta": cur.cheaper_segments - prev.cheaper_segments,
        "expensive_delta": cur.expensive_segments - prev.expensive_segments,
        "unclassified_delta": cur.unclassified_tours - prev.unclassified_tours,
    }
