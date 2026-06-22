"""So sánh đối thủ 1:1 cho Báo cáo BGĐ (theo mẫu BP) — render HTML đẹp, sửa toàn bộ.

Cấu trúc: ĐẦU KHỞI HÀNH (đầu lớn trước) → THỊ TRƯỜNG → đi sâu TỪNG TUYẾN.
3 cột so sánh: VTR | ĐỐI THỦ (mỗi tuyến lấy cty mạnh nhất) | NGANG TẦM (Saigontourist).
  • Giá bán: kèm tên sản phẩm rẻ nhất + link.
  • Tần suất: theo THÁNG, CHỈ từ thời điểm hiện tại trở đi; cột đối thủ lấy ĐỐI THỦ
    MẠNH NHẤT thị trường (không gộp toàn bộ).
HTML đầy đủ (nav nhảy đầu KH + style) → admin sửa toàn bộ qua TinyMCE, lưu AppKv (bền).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from typing import Any

_MIN_PRICE = 500_000
_MAX_PRICE = 500_000_000
_HTML_KEY = "competitor_report_html"
_CONFIG_KEY = "competitor_report_config"
_PEER_KEYWORD = "saigontourist"


def get_config(db) -> dict:
    """Cấu hình báo cáo: đầu khởi hành + THỊ TRƯỜNG được chọn (rỗng = tất cả)."""
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _CONFIG_KEY).first()
    if not row or not row.value_json:
        return {"departures": [], "markets": []}
    try:
        d = json.loads(row.value_json)
        # 'routes' = tên cũ (lọc theo tuyến) → bỏ; giờ lọc theo 'markets' (thị trường).
        return {"departures": d.get("departures") or [], "markets": d.get("markets") or []}
    except json.JSONDecodeError:
        return {"departures": [], "markets": []}


def save_config(db, departures: list, markets: list) -> None:
    from models import AppKv
    payload = json.dumps({"departures": departures or [], "markets": markets or []}, ensure_ascii=False)
    row = db.query(AppKv).filter(AppKv.key == _CONFIG_KEY).first()
    if row:
        row.value_json = payload
    else:
        db.add(AppKv(key=_CONFIG_KEY, value_json=payload))
    db.commit()


def get_report_options(db) -> dict:
    """Lựa chọn cho tab cấu hình: đầu khởi hành (canonical) + THỊ TRƯỜNG (distinct)."""
    from sqlalchemy import distinct
    from models import DepartureAliasRule, Tour
    from tour_filters import market_filter_clause

    deps = sorted({
        r[0].strip() for r in db.query(distinct(DepartureAliasRule.canonical_name))
        .filter(DepartureAliasRule.active == True).all() if r[0] and r[0].strip()  # noqa: E712
    })
    markets = sorted({
        r[0].strip() for r in db.query(distinct(Tour.thi_truong))
        .filter(Tour.thi_truong != "").filter(market_filter_clause(Tour)).all()
        if r[0] and r[0].strip()
    })
    cfg = get_config(db)
    return {
        "departures_options": deps,
        "markets_options": markets,
        "selected_departures": cfg["departures"],
        "selected_markets": cfg["markets"],
    }


def _is_peer(cong_ty: str) -> bool:
    return _PEER_KEYWORD in (cong_ty or "").lower()


def _distinct_products(tours: list) -> int:
    return len({(t.ma_tour or t.ten_tour or "").strip().lower() for t in tours if (t.ma_tour or t.ten_tour)})


def _metrics(tours: list, fdates: dict) -> dict[str, Any]:
    """Gộp 1 nhóm tour (CHỈ tính tour có ngày KH tương lai). Đoàn + tháng từ hiện tại."""
    prods: set[str] = set()
    departures = 0
    price_min: float | None = None
    price_list: list[float] = []
    link = ""
    cheapest_name = ""
    month_count: Counter = Counter()
    for t in tours:
        ds = fdates.get(t.id, [])
        if not ds:
            continue  # không còn ngày KH tương lai → bỏ (giai đoạn từ hiện tại)
        key = (t.ma_tour or "").strip() or (t.ten_tour or "").strip().lower()
        if key:
            prods.add(key)
        departures += len(ds)
        for d in ds:
            month_count[f"{d.year:04d}-{d.month:02d}"] += 1
        if t.gia and _MIN_PRICE <= t.gia <= _MAX_PRICE:
            price_list.append(t.gia)
            if price_min is None or t.gia < price_min:
                price_min = t.gia
                link = t.link_url or ""
                cheapest_name = t.ten_tour or ""
        if not link and t.link_url:
            link = t.link_url
    monthly = [{"month": k, "count": v} for k, v in sorted(month_count.items())]
    return {
        "products": len(prods),
        "departures": departures,
        "price_from": float(price_min) if price_min else None,
        "price_avg": float(sum(price_list) / len(price_list)) if price_list else None,
        "link": link,
        "cheapest_name": cheapest_name,
        "monthly": monthly,
    }


def build_competitor_report(db) -> dict[str, Any]:
    from compare_cache import get_compare_context
    from compare_engine import is_vietravel
    from festival_tagging import _parse_tour_lich_kh
    from classification import _match_departure_alias

    ctx = get_compare_context(db, [], "", "", allow_stale=False)
    tours = ctx.tours
    today = date.today()
    fdates: dict[int, list] = {
        t.id: [d for d in _parse_tour_lich_kh(t.lich_kh or "") if d >= today] for t in tours
    }

    def route_of(t) -> str:
        return (t.tuyen_tour or "").strip() or "Khác"

    # Cấu hình tab "Báo cáo" (Quy tắc phân loại): chỉ báo cáo đầu KH + tuyến được chọn.
    cfg = get_config(db)
    sel_deps = set(cfg.get("departures") or [])
    sel_markets = set(cfg.get("markets") or [])

    by_dep: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for t in tours:
        if not fdates.get(t.id):
            continue  # bỏ tour không còn ngày KH tương lai
        # CHỈ lấy đầu khởi hành chuẩn theo "Quy tắc phân loại" (DepartureAliasRule).
        # diem_kh thô lẫn route/market/rác ("TP.HCM ✈ Sydney", "1 bữa"…) → KHÔNG khớp
        # alias → bỏ khỏi báo cáo.
        dep = _match_departure_alias(t.diem_kh or "")
        if not dep:
            continue
        if sel_deps and dep not in sel_deps:
            continue  # đầu KH không được tick trong cấu hình
        mkt = (t.thi_truong or "").strip() or "Không rõ"
        if sel_markets and mkt not in sel_markets:
            continue  # thị trường không được tick
        by_dep[dep][mkt].append(t)

    dep_counts = {d: sum(len(x) for x in m.values()) for d, m in by_dep.items()}
    dep_order = sorted(by_dep, key=lambda d: -dep_counts[d])

    departures_out: list[dict[str, Any]] = []
    for dep in dep_order:
        markets_out: list[dict[str, Any]] = []
        for mkt, mt in sorted(by_dep[dep].items(), key=lambda kv: -len(kv[1])):
            vtr = [t for t in mt if is_vietravel(t.cong_ty or "")]
            peer = [t for t in mt if _is_peer(t.cong_ty or "")]
            comp_all = [t for t in mt if not is_vietravel(t.cong_ty or "") and not _is_peer(t.cong_ty or "")]

            # Đối thủ MẠNH NHẤT thị trường (cho Giá bán + Tần suất) = nhiều sp nhất.
            comp_by_co_mkt: dict[str, list] = defaultdict(list)
            for t in comp_all:
                comp_by_co_mkt[(t.cong_ty or "(không rõ)")].append(t)
            market_best = max(comp_by_co_mkt, key=lambda c: _distinct_products(comp_by_co_mkt[c])) if comp_by_co_mkt else ""
            comp_best_tours = comp_by_co_mkt.get(market_best, [])

            # Per-route: cty mạnh nhất TỪNG TUYẾN (cho dòng Sản phẩm).
            routes = sorted({route_of(t) for t in mt})
            routes_out: list[dict[str, Any]] = []
            comp_companies: set[str] = set()
            route_best_tours: list = []
            for rt in routes:
                rt_vtr = [t for t in vtr if route_of(t) == rt]
                rt_peer = [t for t in peer if route_of(t) == rt]
                rt_comp = [t for t in comp_all if route_of(t) == rt]
                by_co: dict[str, list] = defaultdict(list)
                for t in rt_comp:
                    by_co[(t.cong_ty or "(không rõ)")].append(t)
                strongest = max(by_co, key=lambda c: _distinct_products(by_co[c])) if by_co else ""
                if strongest:
                    comp_companies.add(strongest)
                rt_best = by_co.get(strongest, [])
                route_best_tours.extend(rt_best)
                if not (rt_vtr or rt_best or rt_peer):
                    continue
                routes_out.append({
                    "tuyen": rt,
                    "vtr": _metrics(rt_vtr, fdates) if rt_vtr else None,
                    "competitor": ({"company": strongest, **_metrics(rt_best, fdates)}) if rt_best else None,
                    "peer": _metrics(rt_peer, fdates) if rt_peer else None,
                })

            markets_out.append({
                "thi_truong": mkt,
                "competitor_companies": sorted(comp_companies),
                "market_best": market_best,
                "has_peer": bool(peer),
                "vtr": _metrics(vtr, fdates),
                "competitor_routeagg": _metrics(route_best_tours, fdates),
                "competitor_best": _metrics(comp_best_tours, fdates),
                "peer": _metrics(peer, fdates),
                "routes": routes_out,
            })
        if markets_out:
            departures_out.append({
                "diem_kh": dep, "total_tours": dep_counts[dep], "markets": markets_out,
            })
    return {"departures": departures_out, "peer_name": "Saigontourist", "generated": today.isoformat()}


# ── HTML render ────────────────────────────────────────────────────────────
def _vnd(n) -> str:
    if not n:
        return "—"
    return f"{round(n):,}".replace(",", ".") + "đ"


def _mlabel(ym: str) -> str:
    return "T" + str(int(ym.split("-")[1]))


def _freq_html(m: dict) -> str:
    if not m.get("monthly"):
        return "<span class='muted'>—</span>"
    months = " · ".join(f"{_mlabel(x['month'])}: {x['count']}" for x in m["monthly"])
    return f"<div class='freq'>{months} đoàn</div>"


def _route_lines(routes: list, pick: str) -> str:
    out = []
    for r in routes:
        m = r.get(pick)
        if not m:
            continue
        co = f" · {m['company']}" if m.get("company") else ""
        link = f" <a href='{m['link']}' target='_blank'>↗</a>" if m.get("link") else ""
        out.append(
            f"<div class='rt'><b>{r['tuyen']}</b><span class='muted'>{co}</span>: từ "
            f"<b class='p'>{_vnd(m['price_from'])}</b> ({m['products']} sp, {m['departures']} đoàn){link}</div>"
        )
    return "".join(out) or "<span class='muted'>—</span>"


def _price_cell(m: dict, avg_label: str) -> str:
    name = f"<div class='muted nm'>{m['cheapest_name']}</div>" if m.get("cheapest_name") else ""
    link = f" <a href='{m['link']}' target='_blank'>↗ link</a>" if m.get("link") else ""
    return (
        f"<div>Giá từ: <b class='p'>{_vnd(m['price_from'])}</b>{link}</div>{name}"
        f"<div class='muted'>{avg_label}: {_vnd(m['price_avg'])}</div>"
    )


def _dep_inner(d: dict, peer: str) -> str:
    """HTML BÊN TRONG 1 section đầu khởi hành (h2 + các card thị trường). Đây là phần
    admin sửa per-đầu (nhỏ → TinyMCE mượt)."""
    cards = []
    for mk in d["markets"]:
        comp_co = mk["market_best"] or "Đối thủ"
        comp_list = (", ".join(mk["competitor_companies"])) if mk["competitor_companies"] else "—"
        rows = f"""
        <tr><th>Sản phẩm</th>
          <td><div class='sum'>{mk['vtr']['products']} sp · {mk['vtr']['departures']} đoàn</div>{_route_lines(mk['routes'],'vtr')}</td>
          <td><div class='sum'>{mk['competitor_routeagg']['products']} sp · {mk['competitor_routeagg']['departures']} đoàn</div>{_route_lines(mk['routes'],'competitor')}</td>
          <td><div class='sum'>{mk['peer']['products']} sp · {mk['peer']['departures']} đoàn</div>{_route_lines(mk['routes'],'peer')}</td></tr>
        <tr><th>Giá bán</th>
          <td>{_price_cell(mk['vtr'],'Giá TB')}</td>
          <td>{_price_cell(mk['competitor_best'],'Giá SS')}</td>
          <td>{_price_cell(mk['peer'],'Giá TB')}</td></tr>
        <tr><th>Tần suất KH</th>
          <td>{_freq_html(mk['vtr'])}</td>
          <td><div class='muted'>Đối thủ mạnh nhất: {comp_co}</div>{_freq_html(mk['competitor_best'])}</td>
          <td>{_freq_html(mk['peer'])}</td></tr>
        <tr><th>Nhận định</th>
          <td colspan='3' class='note'>Nhập nhận định cho thị trường {mk['thi_truong']}…</td></tr>
        """
        cards.append(f"""
        <div class='mkt'>
          <div class='mkt-h'>🌐 {mk['thi_truong']} <span class='muted'>· Đối thủ: {comp_list}</span></div>
          <table>
            <thead><tr><th class='crit'>Tiêu chí</th><th class='vtr'>★ VTR {d['diem_kh']}</th><th>Đối thủ (mạnh nhất/tuyến)</th><th>Ngang tầm · {peer}</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>""")
    return (
        f"<h2>🛫 Khách từ {d['diem_kh']} <span class='muted'>· {d['total_tours']} tour · "
        f"{len(d['markets'])} thị trường</span></h2>" + "".join(cards)
    )


def _css() -> str:
    return """
    *{box-sizing:border-box} body{font-family:'Segoe UI',Arial,sans-serif;color:#1a1a2e;margin:0;background:#f8fafc}
    .page{max-width:1100px;margin:0 auto;padding:24px}
    h1{font-size:22px;color:#003580;margin:0 0 4px} .sub{color:#64748b;font-size:13px;margin-bottom:16px}
    .nav{position:sticky;top:0;background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;margin-bottom:18px;box-shadow:0 1px 4px rgba(0,0,0,.04);z-index:5}
    .nav .lbl{font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px;margin-right:6px}
    .chip{display:inline-block;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:999px;padding:3px 11px;margin:3px;font-size:12px;text-decoration:none;font-weight:600}
    .chip:hover{background:#dbeafe}
    section{margin-bottom:28px;scroll-margin-top:72px}
    h2{font-size:18px;color:#0f172a;border-left:4px solid #003580;padding-left:10px;margin:18px 0 10px}
    .mkt{background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
    .mkt-h{background:linear-gradient(90deg,#003580,#0050b3);color:#fff;padding:9px 14px;font-weight:700;font-size:15px}
    .mkt-h .muted{color:#cfe0ff;font-weight:400;font-size:12px}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th,td{border:1px solid #e8edf3;padding:8px 10px;text-align:left;vertical-align:top}
    thead th{background:#f1f5f9;font-size:12px;color:#475569}
    thead th.vtr{background:#eff6ff;color:#003580}
    th.crit,tbody th{width:96px;background:#f8fafc;font-weight:600;color:#334155}
    .sum{font-weight:700;color:#0f172a;margin-bottom:4px}
    .rt{font-size:11px;line-height:1.5;padding:1px 0;border-top:1px dashed #eef2f7}
    .rt:first-child{border-top:0}
    .p{color:#003580} .muted{color:#94a3b8} .nm{font-size:11px;margin:2px 0}
    .freq{font-size:11px;color:#334155;line-height:1.5}
    td.note{background:#fffbeb;color:#92400e;min-height:36px}
    a{color:#1d4ed8;text-decoration:none} a:hover{text-decoration:underline}
    .top{display:inline-block;margin-top:4px;font-size:11px;color:#94a3b8}
    @media print{.nav{position:static} body{background:#fff}}
    """
def render_full_html(data: dict, saved: dict | None = None) -> str:
    """Báo cáo ĐẦY ĐỦ để XEM: nav nhảy + mọi đầu KH (dùng bản đã sửa per-đầu nếu có)."""
    peer = data.get("peer_name", "Saigontourist")
    deps = data.get("departures", [])
    saved = saved or {}
    nav = " ".join(
        f"<a class='chip' href='#dep-{i}' "
        f"onclick=\"var e=document.getElementById('dep-{i}');if(e){{e.scrollIntoView({{behavior:'smooth',block:'start'}});if(event){{event.preventDefault();}}}}\">"
        f"{d['diem_kh']}</a>"
        for i, d in enumerate(deps)
    )
    sections = []
    for i, d in enumerate(deps):
        body = saved.get(d["diem_kh"]) or _dep_inner(d, peer)
        # 'Lên đầu': dùng scrollTo (anchor '#top' trong srcdoc điều hướng lệch → lỗi).
        sections.append(
            f"<section id='dep-{i}'>{body}"
            f"<a class='top' href='javascript:void(0)' "
            f"onclick=\"(document.scrollingElement||document.documentElement).scrollTo({{top:0,behavior:'smooth'}});if(event){{event.preventDefault();}}\">"
            f"↑ Lên đầu</a></section>"
        )
    return f"""<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8"/>
<title>So sánh đối thủ — Vietravel</title><style>{_css()}</style></head>
<body><div class="page" id="top">
<h1>So sánh đối thủ — Vietravel</h1>
<div class="sub">Cập nhật {data.get('generated','')} · Giai đoạn từ hiện tại · Cột Đối thủ = cty mạnh nhất mỗi tuyến · Ngang tầm = {peer}</div>
<div class="nav"><span class="lbl">Đầu khởi hành:</span>{nav}</div>
{''.join(sections)}
</div></body></html>"""


def render_dep_doc(d: dict, peer: str, saved_body: str | None = None) -> str:
    """1 đầu khởi hành (standalone doc) để SỬA trong TinyMCE — nhỏ → mượt."""
    body = saved_body or _dep_inner(d, peer)
    return (
        f"<!DOCTYPE html><html lang=\"vi\"><head><meta charset=\"utf-8\"/>"
        f"<style>{_css()}</style></head><body><div class=\"page\">{body}</div></body></html>"
    )


def render_competitor_html(data: dict) -> str:  # back-compat
    return render_full_html(data, {})


# ── Persist per-đầu khởi hành (AppKv, bền) ───────────────────────────────────
_DEP_KEY = "competitor_report_dep_html"


def get_dep_map(db) -> dict:
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _DEP_KEY).first()
    if not row or not row.value_json:
        return {}
    try:
        return json.loads(row.value_json)
    except json.JSONDecodeError:
        return {}


def save_dep_html(db, dep_name: str, body: str) -> None:
    from models import AppKv
    m = get_dep_map(db)
    m[dep_name] = body
    payload = json.dumps(m, ensure_ascii=False)
    row = db.query(AppKv).filter(AppKv.key == _DEP_KEY).first()
    if row:
        row.value_json = payload
    else:
        db.add(AppKv(key=_DEP_KEY, value_json=payload))
    db.commit()


# ── Full HTML đã lưu (load NHANH, không build lại mỗi lần) ────────────────────
def get_saved_full(db) -> str | None:
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _HTML_KEY).first()
    return row.value_json if (row and row.value_json) else None


def save_full(db, html: str) -> None:
    from models import AppKv
    row = db.query(AppKv).filter(AppKv.key == _HTML_KEY).first()
    if row:
        row.value_json = html
    else:
        db.add(AppKv(key=_HTML_KEY, value_json=html))
    db.commit()


def clear_dep_map(db) -> None:
    from models import AppKv
    db.query(AppKv).filter(AppKv.key == _DEP_KEY).delete()
    db.commit()


def rebuild_and_save(db) -> str:
    """Dựng lại full HTML (gộp bản sửa per-đầu) + LƯU. Dùng cho 'Làm mới' / daily."""
    html = render_full_html(build_competitor_report(db), get_dep_map(db))
    save_full(db, html)
    return html


def extract_body(html: str) -> str:
    """Lấy phần ruột (.page) từ HTML TinyMCE trả về để lưu per-đầu."""
    import re
    m = re.search(r"<body[^>]*>(.*?)</body>", html or "", re.S | re.I)
    inner = m.group(1) if m else (html or "")
    m2 = re.search(r"<div[^>]*class=['\"]page['\"][^>]*>(.*)</div>", inner, re.S | re.I)
    return (m2.group(1) if m2 else inner).strip()
