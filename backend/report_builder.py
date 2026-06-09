"""Báo cáo CI Vietravel — HTML in đẹp / xuất offline cho BGĐ."""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy.orm import Session

from coverage_engine import build_coverage_summary
from data_quality import compute_data_quality
from models import DailySnapshot


def _fmt(n: float | None) -> str:
    if n is None:
        return "—"
    return f"{n:,.0f}đ"


def _pct(n: float | None) -> str:
    if n is None:
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.1f}%"


def _spark_bar(values: list[float], width: int = 120, height: int = 32) -> str:
    """Tạo SVG bar chart mini nhúng thẳng vào HTML — tương thích in/PDF."""
    if not values:
        return ""
    max_v = max(abs(v) for v in values) or 1
    bar_w = max(2, width // len(values) - 1)
    mid = height // 2
    bars = []
    for i, v in enumerate(values):
        h = int(abs(v) / max_v * (height // 2 - 2))
        x = i * (bar_w + 1)
        if v >= 0:
            bars.append(f'<rect x="{x}" y="{mid - h}" width="{bar_w}" height="{h}" fill="#dc2626" rx="1"/>')
        else:
            bars.append(f'<rect x="{x}" y="{mid}" width="{bar_w}" height="{h}" fill="#16a34a" rx="1"/>')
    baseline = f'<line x1="0" y1="{mid}" x2="{width}" y2="{mid}" stroke="#9ca3af" stroke-width="0.5"/>'
    return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">{baseline}{"".join(bars)}</svg>'


def _trend_line(points: list[tuple[str, float | None]], width: int = 160, height: int = 40) -> str:
    """Line chart mini SVG cho trend 14 ngày."""
    vals = [v for _, v in points if v is not None]
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    coords = []
    for i, (_, v) in enumerate(points):
        if v is None:
            continue
        x = int(i / (len(points) - 1) * (width - 4)) + 2
        y = int((1 - (v - mn) / rng) * (height - 6)) + 3
        coords.append(f"{x},{y}")
    polyline = f'<polyline points="{" ".join(coords)}" fill="none" stroke="#003580" stroke-width="1.5"/>'
    return f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"><rect width="{width}" height="{height}" fill="#f8fafc" rx="3"/>{polyline}</svg>'


def build_report_html(db: Session, report_type: str = "daily") -> str:
    """Báo cáo BGĐ HTML — cache 5 phút Redis.

    Cold start fix: nếu compare cache cold (sau restart), trả version simplified
    từ DailySnapshot thay vì block đợi 40s prewarm. Lần kế tiếp cache warm → full report.
    """
    # Redis cache HTML response — 5 phút TTL
    from redis_cache import make_key, redis_get, redis_set

    cache_key = make_key("report.html", type=report_type)
    cached_html = redis_get(cache_key)
    if cached_html is not None:
        return cached_html

    daily = db.query(DailySnapshot).order_by(DailySnapshot.snapshot_date.desc()).first()

    # Lấy snapshot trước để so sánh
    prev = None
    if daily:
        prev = (
            db.query(DailySnapshot)
            .filter(DailySnapshot.snapshot_date < daily.snapshot_date)
            .order_by(DailySnapshot.snapshot_date.desc())
            .first()
        )

    # COLD START: nếu cache cold, trả disk version (full report từ lần compute trước, < 24h)
    from compare_cache import _cache as _compare_in_mem
    if not _compare_in_mem:
        from persistent_cache import load_text
        disk_html = load_text(f"report_{report_type}", max_age_hours=24)
        if disk_html:
            return disk_html
        # First-time chưa có disk → tạm trả simplified
        from datetime import date as _date
        snap_date = daily.snapshot_date.isoformat() if daily else _date.today().isoformat()
        title = "Báo cáo CI Vietravel — Hàng ngày" if report_type == "daily" else "Báo cáo CI Vietravel — Tuần"
        return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:system-ui,sans-serif;padding:32px;max-width:900px;margin:auto;}}
.notice{{padding:14px 18px;border-radius:8px;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;}}
.kpi{{display:inline-block;padding:12px 18px;margin:4px;border-radius:8px;background:#f3f4f6;}}
.kpi b{{display:block;font-size:24px;color:#1d4ed8;}}</style></head><body>
<h1>{title}</h1><p>Snapshot: {snap_date}</p>
<div class="notice">⏳ Lần đầu khởi tạo — đang build full report (~40s). F5 reload sau 1 phút.</div>
<div><div class="kpi"><b>{daily.total_tours if daily else 0}</b>Tổng tour</div>
<div class="kpi"><b>{daily.vtr_tours if daily else 0}</b>VTR tour</div>
<div class="kpi"><b>{daily.segment_count if daily else 0}</b>Phân khúc</div></div>
</body></html>"""

    from compare_cache import get_compare_context

    ctx = get_compare_context(db, [], "", "")
    tours = ctx.tours
    segments = ctx.segments
    quality = compute_data_quality(db, tours)
    coverage = build_coverage_summary(tours)

    try:
        insights = json.loads(daily.insights_json or "[]") if daily else []
    except json.JSONDecodeError:
        insights = []

    # Phân loại segments
    expensive = sorted(
        [s for s in segments if s.gap_pct is not None and s.gap_pct >= 5],
        key=lambda s: s.gap_pct or 0, reverse=True,
    )[:12]
    cheap = sorted(
        [s for s in segments if s.gap_pct is not None and s.gap_pct <= -5],
        key=lambda s: s.gap_pct or 0,
    )[:8]
    freq_lag = sorted(
        [s for s in segments if s.freq_gap_pct is not None and s.freq_gap_pct <= -20 and s.vtr_entries],
        key=lambda s: s.freq_gap_pct or 0,
    )[:8]

    snap_date = daily.snapshot_date.isoformat() if daily else date.today().isoformat()
    title = "Báo cáo CI Vietravel — Hàng ngày" if report_type == "daily" else "Báo cáo CI Vietravel — Tuần"

    # KPI LẤY LIVE (cùng nguồn So sánh) → số liệu khớp module So sánh.
    # prev_* vẫn lấy từ snapshot hôm qua để tính delta ngày-qua-ngày.
    from compare_engine import summarize_context

    live_kpi = summarize_context(tours, segments)
    kpi_avg_gap = live_kpi["avg_gap_pct"]
    kpi_expensive = live_kpi["expensive"]
    kpi_cheaper = live_kpi["cheaper"]
    kpi_segment = live_kpi["segment_count"]
    kpi_freq_lag = live_kpi["freq_lagging"]
    kpi_unclassified = getattr(daily, "unclassified_tours", 0) if daily else 0

    prev_gap = getattr(prev, "avg_gap_pct", None) if prev else None
    prev_expensive = getattr(prev, "expensive_segments", None) if prev else None
    prev_cheaper = getattr(prev, "cheaper_segments", None) if prev else None

    def _delta_txt(cur, prev_val, unit="", good_direction="down"):
        if cur is None or prev_val is None:
            return ""
        d = cur - prev_val
        if d == 0:
            return '<span style="color:#6b7280;font-size:11px">→ Không đổi</span>'
        sign = "+" if d > 0 else ""
        good = (d < 0) if good_direction == "down" else (d > 0)
        color = "#16a34a" if good else "#dc2626"
        arrow = "▼" if d < 0 else "▲"
        return f'<span style="color:{color};font-size:11px">{arrow} {sign}{d:.1f}{unit} vs hôm qua</span>'

    # Trend 14 ngày cho sparkline
    from snapshot_service import get_trend
    trend_data = get_trend(db, 14)
    trend_points = [(r["date"], r.get("avg_gap_pct")) for r in trend_data]
    trend_svg = _trend_line(trend_points)

    # Bar spark cho top đắt
    expensive_gap_vals = [s.gap_pct for s in expensive[:8] if s.gap_pct is not None]
    spark_exp = _spark_bar(expensive_gap_vals)

    # Executive summary
    action_items = []
    if kpi_expensive >= 3:
        action_items.append(f"<li>Rà soát giá <strong>{kpi_expensive} tuyến đắt hơn TT ≥5%</strong> — ưu tiên cao nhất</li>")
    if kpi_freq_lag >= 2:
        action_items.append(f"<li>Bổ sung lịch KH cho <strong>{kpi_freq_lag} tuyến ít đoàn hơn đối thủ</strong></li>")
    gaps = coverage.get("gaps", [])
    if gaps:
        action_items.append(f"<li>Đánh giá <strong>{len(gaps)} tuyến khoảng trống</strong> — TT có SP, VTR chưa có</li>")
    if kpi_unclassified > 50:
        action_items.append(f"<li>Phân loại <strong>{kpi_unclassified} tour chưa có Thị trường/Tuyến</strong></li>")

    exec_gap_sentence = ""
    if kpi_avg_gap is not None:
        if kpi_avg_gap >= 5:
            exec_gap_sentence = f"Chênh giá TB <strong>{_pct(kpi_avg_gap)}</strong> — VTR đang ở mức premium so với thị trường."
        elif kpi_avg_gap <= -5:
            exec_gap_sentence = f"Chênh giá TB <strong>{_pct(kpi_avg_gap)}</strong> — VTR đang có lợi thế giá."
        else:
            exec_gap_sentence = f"Chênh giá TB <strong>{_pct(kpi_avg_gap)}</strong> — VTR gần ngang giá thị trường."
    trend_direction = ""
    if prev_gap is not None and kpi_avg_gap is not None:
        diff = kpi_avg_gap - prev_gap
        if diff > 1:
            trend_direction = "Xu hướng: chênh giá đang nới rộng so với hôm qua."
        elif diff < -1:
            trend_direction = "Xu hướng: chênh giá đang thu hẹp so với hôm qua."

    rows_exp = "".join(
        f"<tr>"
        f"<td>{s.thi_truong}</td><td>{s.tuyen_tour}</td><td>{s.diem_kh}</td>"
        f"<td style='text-align:center'>{s.so_ngay:.0f}N</td>"
        f"<td style='text-align:right'>{_fmt(s.vtr_avg_price)}</td>"
        f"<td style='text-align:right'>{_fmt(s.comparison_price)}</td>"
        f"<td style='text-align:center;color:{'#dc2626' if (s.gap_pct or 0)>=15 else '#ea580c'};font-weight:bold'>{_pct(s.gap_pct)}</td>"
        f"</tr>"
        for s in expensive
    )
    rows_cheap = "".join(
        f"<tr><td>{s.tuyen_tour}</td><td>{s.diem_kh}</td><td>{s.thi_truong}</td>"
        f"<td style='text-align:center'>{s.so_ngay:.0f}N</td>"
        f"<td style='text-align:right'>{_fmt(s.vtr_avg_price)}</td>"
        f"<td style='text-align:right'>{_fmt(s.comparison_price)}</td>"
        f"<td style='text-align:center;color:#16a34a;font-weight:bold'>{_pct(s.gap_pct)}</td></tr>"
        for s in cheap
    )
    rows_freq = "".join(
        f"<tr><td>{s.tuyen_tour}</td><td>{s.diem_kh}</td><td>{s.thi_truong}</td>"
        f"<td style='text-align:center'>{round(getattr(s, 'vtr_avg_departures_per_month', None) or s.vtr_freq_monthly, 1)}</td>"
        f"<td style='text-align:center'>{round(s.market_freq_avg_per_company or 0, 1)}</td>"
        f"<td style='text-align:center;color:#d97706;font-weight:bold'>{_pct(s.freq_gap_pct)}</td>"
        f"</tr>"
        for s in freq_lag
    )
    gap_rows = "".join(
        f"<tr><td>{g['thi_truong']}</td><td>{g['tuyen_tour']}</td>"
        f"<td style='text-align:center'>{g['market_tours']}</td>"
        f"<td style='text-align:center'>{g['companies']}</td>"
        f"<td style='text-align:center'>{g.get('market_departures_monthly','—')}</td>"
        f"</tr>"
        for g in gaps[:12]
    )
    insight_items = "".join(
        f"<li><strong>[{i.get('category','').upper()}]</strong> {i.get('title','')} — <em>{i.get('description','')}</em></li>"
        for i in insights[:10]
    )

    final_html = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; color: #1a1a2e; background: #fff; }}
  .page {{ max-width: 960px; margin: 0 auto; padding: 40px 32px; }}
  .header {{ border-bottom: 3px solid #003580; padding-bottom: 16px; margin-bottom: 24px; }}
  .header h1 {{ font-size: 22px; font-weight: 700; color: #003580; }}
  .header .meta {{ font-size: 12px; color: #64748b; margin-top: 4px; }}

  /* Executive summary */
  .exec-box {{ background: #eff6ff; border-left: 4px solid #003580; border-radius: 6px; padding: 16px 20px; margin-bottom: 24px; }}
  .exec-box p {{ margin-bottom: 8px; line-height: 1.6; }}
  .exec-box ul {{ margin-left: 18px; margin-top: 8px; }}
  .exec-box ul li {{ margin-bottom: 5px; }}

  /* KPI grid */
  .kpis {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }}
  .kpi {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; }}
  .kpi .val {{ font-size: 26px; font-weight: 700; color: #003580; }}
  .kpi .lbl {{ font-size: 11px; color: #64748b; margin-top: 3px; }}
  .kpi .delta {{ margin-top: 4px; }}
  .kpi-danger .val {{ color: #dc2626; }}
  .kpi-good .val {{ color: #16a34a; }}
  .kpi-warn .val {{ color: #d97706; }}

  /* Section */
  h2 {{ font-size: 15px; font-weight: 700; color: #1a75d2; margin: 28px 0 12px; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
  h3 {{ font-size: 13px; font-weight: 600; color: #374151; margin: 20px 0 8px; }}

  /* Tables */
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 8px 0; }}
  thead th {{ background: #003580; color: #fff; padding: 7px 8px; text-align: left; font-weight: 600; }}
  tbody td {{ border-bottom: 1px solid #e5e7eb; padding: 7px 8px; vertical-align: middle; }}
  tbody tr:nth-child(even) {{ background: #f9fafb; }}
  tbody tr:hover {{ background: #eff6ff; }}
  .danger-row {{ background: #fef2f2 !important; }}
  .warn-row {{ background: #fffbeb !important; }}
  .good-row {{ background: #f0fdf4 !important; }}

  /* Trend */
  .trend-box {{ display: flex; align-items: center; gap: 16px; background: #f8fafc; border-radius: 6px; padding: 12px 16px; }}

  /* Insights */
  .insights ol {{ margin-left: 18px; }}
  .insights li {{ margin: 6px 0; line-height: 1.5; }}

  /* Footer */
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #e2e8f0; font-size: 11px; color: #9ca3af; text-align: center; }}

  @media print {{
    body {{ font-size: 12px; }}
    .page {{ padding: 20px; }}
    .no-print {{ display: none !important; }}
    h2 {{ page-break-after: avoid; }}
    table {{ page-break-inside: avoid; }}
  }}
</style></head>
<body><div class="page">

<div class="header">
  <h1>{title}</h1>
  <p class="meta">Ngày báo cáo: {snap_date} &nbsp;·&nbsp; OTA Research Platform &nbsp;·&nbsp; {kpi_segment} nhóm so sánh &nbsp;·&nbsp; {_fmt(None).replace('—',str(len(tours)))} tour</p>
</div>

<!-- Executive Summary -->
<div class="exec-box">
  <p><strong>Tóm tắt:</strong> {exec_gap_sentence} {trend_direction}
    Có <strong>{kpi_expensive}</strong> nhóm VTR đắt hơn TT và <strong>{kpi_cheaper}</strong> nhóm VTR rẻ hơn.
    Tần suất KH: {kpi_freq_lag} tuyến VTR ít đoàn hơn đối thủ ≥20%.
  </p>
  {'<p><strong>Cần hành động:</strong></p><ul>' + ''.join(action_items) + '</ul>' if action_items else ''}
</div>

<!-- KPIs -->
<div class="kpis">
  <div class="kpi {'kpi-danger' if (kpi_avg_gap or 0)>=5 else 'kpi-good' if (kpi_avg_gap or 0)<=-5 else ''}">
    <div class="val">{_pct(kpi_avg_gap)}</div>
    <div class="lbl">Chênh giá TB VTR vs thị trường</div>
    <div class="delta">{_delta_txt(kpi_avg_gap, prev_gap, '%', 'down')}</div>
  </div>
  <div class="kpi kpi-danger">
    <div class="val">{kpi_expensive}</div>
    <div class="lbl">Nhóm VTR đắt hơn TT (≥5%)</div>
    <div class="delta">{_delta_txt(kpi_expensive, prev_expensive, '', 'down')}</div>
  </div>
  <div class="kpi kpi-good">
    <div class="val">{kpi_cheaper}</div>
    <div class="lbl">Nhóm VTR rẻ hơn TT (≤−5%)</div>
    <div class="delta">{_delta_txt(kpi_cheaper, prev_cheaper, '', 'up')}</div>
  </div>
  <div class="kpi">
    <div class="val">{kpi_freq_lag}</div>
    <div class="lbl">Tuyến VTR thiếu lịch KH</div>
  </div>
  <div class="kpi">
    <div class="val">{len(gaps)}</div>
    <div class="lbl">Khoảng trống phủ sóng</div>
  </div>
  <div class="kpi {'kpi-warn' if kpi_unclassified>50 else ''}">
    <div class="val">{kpi_unclassified}</div>
    <div class="lbl">Tour chưa phân loại</div>
  </div>
</div>

<!-- Trend mini -->
{f'''<div class="trend-box">
  <div>{trend_svg}</div>
  <div style="font-size:12px;color:#374151">
    <strong>Xu hướng 14 ngày</strong> — Chênh giá TB<br/>
    <span style="color:#64748b">Từ {trend_data[0]['date'] if trend_data else '—'} đến {snap_date}</span>
  </div>
</div>''' if trend_data else ''}

<h2>I. Phân tích Giá — VTR đắt hơn thị trường</h2>
{f'<p style="margin-bottom:8px">Biểu đồ chênh lệch: {spark_exp}</p>' if spark_exp else ''}
<table>
  <thead><tr><th>Thị trường</th><th>Tuyến tour</th><th>Điểm KH</th><th style="text-align:center">Ngày</th><th style="text-align:right">Giá VTR</th><th style="text-align:right">Giá SS</th><th style="text-align:center">Chênh</th></tr></thead>
  <tbody>
    {rows_exp or '<tr><td colspan="7" style="text-align:center;color:#6b7280">Không có tuyến đắt hơn TT ≥5%</td></tr>'}
  </tbody>
</table>

<h3>VTR rẻ hơn thị trường (lợi thế giá)</h3>
<table>
  <thead><tr><th>Tuyến tour</th><th>Điểm KH</th><th>Thị trường</th><th style="text-align:center">Ngày</th><th style="text-align:right">Giá VTR</th><th style="text-align:right">Giá SS</th><th style="text-align:center">Chênh</th></tr></thead>
  <tbody>
    {rows_cheap or '<tr><td colspan="7" style="text-align:center;color:#6b7280">Không có</td></tr>'}
  </tbody>
</table>

<h2>II. Tần suất Khởi hành — VTR vs đối thủ</h2>
<table>
  <thead><tr><th>Tuyến tour</th><th>Điểm KH</th><th>Thị trường</th><th style="text-align:center">VTR đoàn/tháng</th><th style="text-align:center">TT tb/CT</th><th style="text-align:center">Gap TS</th></tr></thead>
  <tbody>
    {rows_freq or '<tr><td colspan="6" style="text-align:center;color:#6b7280">Không có tuyến thiếu lịch KH nghiêm trọng</td></tr>'}
  </tbody>
</table>
<p style="font-size:11px;color:#6b7280;margin-top:6px">Gap TS: % chênh tần suất VTR so với TB đối thủ trên cùng tuyến. Âm = VTR ít lịch hơn.</p>

<h2>III. Phủ sóng — Khoảng trống (TT có SP, VTR chưa có)</h2>
<table>
  <thead><tr><th>Thị trường</th><th>Tuyến tour</th><th style="text-align:center">SP thị trường</th><th style="text-align:center">Số ĐT</th><th style="text-align:center">Đoàn TT/tháng</th></tr></thead>
  <tbody>
    {gap_rows or '<tr><td colspan="5" style="text-align:center;color:#6b7280">Không phát hiện khoảng trống đáng kể</td></tr>'}
  </tbody>
</table>

<h2>IV. Insight tự động</h2>
<div class="insights">
  <ol>{insight_items or '<li>Không có insight mới — thử chụp snapshot</li>'}</ol>
</div>

<div class="footer no-print">
  Mẹo: In trang này (Ctrl+P) → chọn <strong>Save as PDF</strong> để gửi offline cho BGĐ.
</div>

</div></body></html>"""
    # Cache final report: Redis 5 phút + Disk 24h (survive restart)
    try:
        redis_set(cache_key, final_html, ttl=300)
        from persistent_cache import save_text
        save_text(f"report_{report_type}", final_html, ttl_hours=24)
    except Exception:  # noqa: BLE001
        pass
    return final_html
