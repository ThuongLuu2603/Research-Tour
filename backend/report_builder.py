"""Báo cáo CI — HTML in đẹp / xuất offline."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from compare_engine import build_segment_stats, deduplicate_tours
from coverage_engine import build_coverage_summary
from data_quality import compute_data_quality
from models import DailySnapshot, Tour


def _fmt(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{n:,.0f}đ"


def build_report_html(db: Session, report_type: str = "daily") -> str:
    daily = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).first()
    tours = db.query(Tour).filter(Tour.gia != None, Tour.gia > 0).all()  # noqa: E711
    tours = deduplicate_tours(tours)
    segments = build_segment_stats(tours, dedup=False)
    quality = compute_data_quality(db, tours)
    coverage = build_coverage_summary(tours)

    try:
        insights = json.loads(daily.insights_json or "[]") if daily else []
    except json.JSONDecodeError:
        insights = []

    expensive = sorted(
        [s for s in segments if s.gap_pct is not None and s.gap_pct >= 5],
        key=lambda s: s.gap_pct or 0, reverse=True,
    )[:12]
    cheap = sorted(
        [s for s in segments if s.gap_pct is not None and s.gap_pct <= -5],
        key=lambda s: s.gap_pct or 0,
    )[:8]

    snap_date = daily.snapshot_date.isoformat() if daily else date.today().isoformat()
    title = "Báo cáo CI Vietravel — Hàng ngày" if report_type == "daily" else "Báo cáo CI Vietravel — Tuần"

    rows_exp = "".join(
        f"<tr><td>{s.thi_truong}</td><td>{s.tuyen_tour}</td><td>{s.diem_kh}</td>"
        f"<td>{s.so_ngay:.0f}N</td><td>{_fmt(s.vtr_avg_price)}</td><td>{_fmt(s.comparison_price)}</td>"
        f"<td><strong>{s.gap_pct}%</strong></td></tr>"
        for s in expensive
    )
    rows_cheap = "".join(
        f"<tr><td>{s.tuyen_tour}</td><td>{s.diem_kh}</td><td>{s.gap_pct}%</td></tr>"
        for s in cheap
    )
    insight_items = "".join(
        f"<li><strong>[{i.get('category','')}]</strong> {i.get('title','')} — {i.get('description','')}</li>"
        for i in insights[:10]
    )
    gap_rows = "".join(
        f"<tr><td>{g['thi_truong']}</td><td>{g['tuyen_tour']}</td><td>{g['market_tours']}</td><td>{g['companies']}</td></tr>"
        for g in coverage.get("gaps", [])[:10]
    )

    kpi = daily or type("X", (), {
        "avg_gap_pct": None, "cheaper_segments": 0, "expensive_segments": 0,
        "segment_count": len(segments), "vtr_tours": quality["vtr_tours"],
        "unclassified_tours": quality["unclassified_count"],
    })()

    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; color: #1a1a2e; }}
  h1 {{ color: #003580; border-bottom: 3px solid #003580; padding-bottom: 8px; }}
  h2 {{ color: #1a75d2; margin-top: 28px; }}
  .meta {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  .kpis {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
  .kpi {{ background: #f0f6ff; border-radius: 8px; padding: 16px; text-align: center; }}
  .kpi .val {{ font-size: 28px; font-weight: bold; color: #003580; }}
  .kpi .lbl {{ font-size: 12px; color: #666; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 12px 0; }}
  th {{ background: #003580; color: white; padding: 8px; text-align: left; }}
  td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  .insights li {{ margin: 8px 0; line-height: 1.5; }}
  @media print {{ body {{ margin: 20px; }} .no-print {{ display: none; }} }}
</style></head><body>
<h1>{title}</h1>
<p class="meta">Ngày báo cáo: {snap_date} · OTA Research Platform · Ưu tiên: Giá → Tần suất → Phủ sóng</p>

<div class="kpis">
  <div class="kpi"><div class="val">{getattr(kpi, 'avg_gap_pct', None) or '—'}%</div><div class="lbl">Chênh giá TB VTR</div></div>
  <div class="kpi"><div class="val">{getattr(kpi, 'expensive_segments', 0)}</div><div class="lbl">Nhóm VTR đắt hơn TT</div></div>
  <div class="kpi"><div class="val">{getattr(kpi, 'cheaper_segments', 0)}</div><div class="lbl">Nhóm VTR rẻ hơn TT</div></div>
  <div class="kpi"><div class="val">{quality['classified_pct']}%</div><div class="lbl">Tour phân loại OK</div></div>
</div>

<h2>Insight hôm nay</h2>
<ul class="insights">{insight_items or '<li>Không có insight mới</li>'}</ul>

<h2>Top segment VTR đắt hơn thị trường (Giá)</h2>
<table><thead><tr><th>Thị trường</th><th>Tuyến</th><th>Điểm KH</th><th>Ngày</th><th>Giá VTR</th><th>Giá SS</th><th>Chênh %</th></tr></thead>
<tbody>{rows_exp or '<tr><td colspan="7">Không có</td></tr>'}</tbody></table>

<h2>Top segment VTR rẻ hơn thị trường</h2>
<table><thead><tr><th>Tuyến</th><th>Điểm KH</th><th>Chênh %</th></tr></thead>
<tbody>{rows_cheap or '<tr><td colspan="3">Không có</td></tr>'}</tbody></table>

<h2>Khoảng trống phủ sóng (TT có, VTR chưa có)</h2>
<table><thead><tr><th>Thị trường</th><th>Tuyến</th><th>SP thị trường</th><th>Công ty</th></tr></thead>
<tbody>{gap_rows or '<tr><td colspan="4">Không phát hiện</td></tr>'}</tbody></table>

<p class="meta no-print" style="margin-top:40px">In trang này (Ctrl+P) để xuất PDF offline cho BGĐ.</p>
</body></html>"""
