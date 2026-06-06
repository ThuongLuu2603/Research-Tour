"""Insight & alert engine — ưu tiên Giá > Tần suất > Phủ sóng."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from compare_engine import build_segment_stats, deduplicate_tours, is_vietravel
from coverage_engine import build_coverage_summary
from data_quality import compute_data_quality
from models import DailySnapshot, IntelAlert, SegmentSnapshot, Tour


def _fmt(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{n:,.0f}đ"


def generate_insights(db: Session, tours: list[Tour], daily: DailySnapshot) -> str:
    tours = deduplicate_tours(tours)
    segments = build_segment_stats(tours, dedup=False)
    quality = compute_data_quality(db, tours)
    coverage = build_coverage_summary(tours)
    insights: list[dict] = []

    expensive = [s for s in segments if s.gap_pct is not None and s.gap_pct >= 10]
    expensive.sort(key=lambda s: s.gap_pct or 0, reverse=True)
    for s in expensive[:5]:
        insights.append({
            "id": f"price-high-{s.key}",
            "category": "price",
            "severity": "warning" if (s.gap_pct or 0) >= 15 else "info",
            "title": f"VTR đắt hơn TT {s.gap_pct}% — {s.tuyen_tour}",
            "description": f"{s.thi_truong} · {s.diem_kh} · {s.so_ngay:.0f}N · Giá SS {_fmt(s.comparison_price)}",
            "link_path": "/compare",
            "link_params": {"tab": "price", "tuyen": s.tuyen_tour},
            "priority": 1,
        })

    cheap = [s for s in segments if s.gap_pct is not None and s.gap_pct <= -10]
    cheap.sort(key=lambda s: s.gap_pct or 0)
    for s in cheap[:3]:
        insights.append({
            "id": f"price-low-{s.key}",
            "category": "price",
            "severity": "info",
            "title": f"VTR rẻ hơn TT {s.gap_pct}% — {s.tuyen_tour}",
            "description": f"{s.thi_truong} · {s.diem_kh} · lợi thế giá",
            "link_path": "/compare",
            "link_params": {"tab": "price"},
            "priority": 2,
        })

    freq_lag = [s for s in segments if s.freq_gap_pct is not None and s.freq_gap_pct <= -25]
    freq_lag.sort(key=lambda s: s.freq_gap_pct or 0)
    for s in freq_lag[:3]:
        insights.append({
            "id": f"freq-lag-{s.key}",
            "category": "frequency",
            "severity": "warning",
            "title": f"Ít đoàn hơn đối thủ {s.freq_gap_pct}% — {s.tuyen_tour}",
            "description": f"TB đoàn/tháng VTR {s.vtr_avg_departures_per_month} vs TT {s.market_freq_avg_per_company}",
            "link_path": "/compare",
            "link_params": {"tab": "frequency"},
            "priority": 3,
        })

    for cell in coverage.get("gaps", [])[:4]:
        insights.append({
            "id": f"coverage-{cell['thi_truong']}-{cell['tuyen_tour']}",
            "category": "coverage",
            "severity": "info",
            "title": f"Khoảng trống: {cell['tuyen_tour']} ({cell['thi_truong']})",
            "description": f"Thị trường có {cell['market_tours']} SP, VTR chưa có tour",
            "link_path": "/compare",
            "link_params": {"tab": "coverage"},
            "priority": 4,
        })

    if quality["unclassified_pct"] > 5:
        insights.append({
            "id": "quality-unclassified",
            "category": "quality",
            "severity": "warning",
            "title": f"{quality['unclassified_count']} tour chưa phân loại đủ ({quality['unclassified_pct']}%)",
            "description": "Cần gán Thị trường / Tuyến tour hoặc bổ sung rules",
            "link_path": "/data",
            "link_params": {"filter": "unclassified"},
            "priority": 5,
        })

    insights.sort(key=lambda x: x.get("priority", 99))
    return json.dumps(insights, ensure_ascii=False)


def generate_alerts(db: Session, tours: list[Tour], daily: DailySnapshot, insights_json: str) -> None:
    db.query(IntelAlert).filter(
        IntelAlert.created_at >= datetime.utcnow() - timedelta(days=1),
        IntelAlert.alert_type == "daily_insight",
    ).delete()

    try:
        insights = json.loads(insights_json)
    except json.JSONDecodeError:
        insights = []

    for ins in insights[:15]:
        db.add(IntelAlert(
            alert_type="daily_insight",
            severity=ins.get("severity", "info"),
            category=ins.get("category", "price"),
            title=ins.get("title", ""),
            message=ins.get("description", ""),
            link_path=ins.get("link_path", "/"),
            payload_json=json.dumps(ins.get("link_params") or {}, ensure_ascii=False),
        ))

    prev = (
        db.query(DailySnapshot)
        .filter(DailySnapshot.snapshot_date < daily.snapshot_date)
        .order_by(DailySnapshot.snapshot_date.desc())
        .first()
    )
    if prev and daily.avg_gap_pct is not None and prev.avg_gap_pct is not None:
        delta = daily.avg_gap_pct - prev.avg_gap_pct
        if abs(delta) >= 3:
            db.add(IntelAlert(
                alert_type="price_trend",
                severity="warning" if delta > 0 else "info",
                category="price",
                title=f"Chênh giá TB thay đổi {delta:+.1f} điểm %",
                message=f"Từ {prev.avg_gap_pct}% → {daily.avg_gap_pct}% so với hôm qua",
                link_path="/compare",
            ))

    db.commit()


def get_home_brief(db: Session) -> dict:
    daily = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).first()
    if not daily:
        from snapshot_service import capture_daily_snapshot
        from tour_sources import apply_market_compare_source_filter
        from db_retry import run_with_retry

        tours = apply_market_compare_source_filter(
            db.query(Tour).filter(Tour.gia != None, Tour.gia > 0)  # noqa: E711
        ).all()
        daily = run_with_retry(lambda: capture_daily_snapshot(db, tours), db=db, label="brief-snapshot")

    try:
        insights = json.loads(daily.insights_json or "[]")
    except json.JSONDecodeError:
        insights = []

    alerts = (
        db.query(IntelAlert)
        .filter(IntelAlert.is_read == False)
        .order_by(IntelAlert.created_at.desc())
        .limit(20)
        .all()
    )

    # KPI LẤY TỪ NGUỒN LIVE GIỐNG MODULE SO SÁNH (cùng cache get_compare_context) → luôn khớp nhau,
    # không còn lệch do snapshot chụp 1 lần/ngày. Insights/alerts/trend vẫn lấy từ snapshot (lịch sử).
    kpis = {
        "total_tours": daily.total_tours,
        "vtr_tours": daily.vtr_tours,
        "segment_count": daily.segment_count,
        "cheaper_segments": daily.cheaper_segments,
        "expensive_segments": daily.expensive_segments,
        "avg_gap_pct": daily.avg_gap_pct,
        "freq_leading": daily.freq_leading_segments,
        "freq_lagging": daily.freq_lagging_segments,
        "unclassified_tours": daily.unclassified_tours,
        "flagged_tours": daily.flagged_tours,
    }
    kpis_source = "snapshot"
    try:
        from compare_cache import get_compare_context
        from compare_engine import summarize_context

        ctx = get_compare_context(db, [], "", "")
        live = summarize_context(ctx.tours, ctx.segments)
        kpis.update({
            "total_tours": live["total_tours"],
            "vtr_tours": live["vtr_count"],
            "segment_count": live["segment_count"],
            "cheaper_segments": live["cheaper"],
            "expensive_segments": live["expensive"],
            "avg_gap_pct": live["avg_gap_pct"],
            "freq_leading": live["freq_leading"],
            "freq_lagging": live["freq_lagging"],
        })
        kpis_source = "live"
    except Exception:
        pass  # lỗi build context → giữ KPI snapshot làm fallback

    from snapshot_service import delta_vs_previous, get_trend
    return {
        "snapshot_date": daily.snapshot_date.isoformat(),
        "kpis_source": kpis_source,
        "kpis": kpis,
        "delta": delta_vs_previous(db),
        "trend": get_trend(db, 14),
        "insights": insights,
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "category": a.category,
                "title": a.title,
                "message": a.message,
                "link_path": a.link_path,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    }
