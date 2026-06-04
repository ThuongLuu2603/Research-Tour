"""Đồng bộ quy tắc phân loại giữa DB và Google Sheet (2 chiều)."""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from config import settings

logger = logging.getLogger(__name__)

SHEET_ID = settings.sheet_id
GID_ROUTE_RULES = 58839224
MARKET_RULES_SHEET = "Quy tắc Thị trường"


def _client():
    from google_auth import get_gspread_client
    return get_gspread_client()


def _route_worksheet():
    gc = _client()
    return gc.open_by_key(SHEET_ID).get_worksheet_by_id(GID_ROUTE_RULES)


def _market_worksheet():
    gc = _client()
    sh = gc.open_by_key(SHEET_ID)
    try:
        return sh.worksheet(MARKET_RULES_SHEET)
    except Exception:
        return sh.add_worksheet(MARKET_RULES_SHEET, rows=500, cols=4)


# ── Route rules ───────────────────────────────────────────────────────────────

def pull_route_rules_from_sheet() -> dict[str, list[dict]]:
    """Đọc sheet 'Điểm tuyến Tour' — cùng format route_rules.load_route_rules()."""
    ws = _route_worksheet()
    data = ws.get_all_values()
    rules: dict[str, list[dict]] = {}
    for row in data[2:]:
        if not row or not row[0].strip():
            continue
        market = row[0].strip()
        route = row[1].strip() if len(row) > 1 else market
        for cell in row[2:]:
            if cell and str(cell).strip():
                kws = [k.strip().lower() for k in str(cell).split(",") if k.strip()]
                if kws:
                    rules.setdefault(market, []).append({"route": route, "keywords": kws})
    return rules


def import_route_rules_to_db(db: Session) -> int:
    from models import RouteKeywordRule
    from classification import invalidate_rules_changed

    raw = pull_route_rules_from_sheet()
    db.query(RouteKeywordRule).delete()
    count = order = 0
    for market, rule_list in raw.items():
        for rule in rule_list:
            kws = ", ".join(rule.get("keywords", []))
            if not kws:
                continue
            db.add(RouteKeywordRule(
                thi_truong=market,
                tuyen_tour=rule.get("route", market),
                keywords=kws,
                sort_order=order,
            ))
            count += 1
            order += 1
    db.commit()
    invalidate_rules_changed(db)
    return count


def push_route_rules_to_sheet(db: Session) -> int:
    """Ghi quy tắc tuyến tour từ DB lên Google Sheet."""
    from models import RouteKeywordRule

    rules = (
        db.query(RouteKeywordRule)
        .filter(RouteKeywordRule.active == True)  # noqa: E712
        .order_by(RouteKeywordRule.sort_order, RouteKeywordRule.id)
        .all()
    )
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rules:
        grouped[(r.thi_truong, r.tuyen_tour)].append(r.keywords)

    header1 = ["Thị trường", "Tuyến tour", "Giá trị 1", "Giá trị 2", "Giá trị 3", "Giá trị 4", "Giá trị 5"]
    header2 = ["", "", "Keywords (AND trong cột)", "", "", "", ""]
    rows = [header1, header2]
    for (market, route), kw_cols in sorted(grouped.items()):
        rows.append([market, route] + kw_cols)

    ws = _route_worksheet()
    ws.clear()
    ws.update(rows, "A1")
    return len(rules)


# ── Market rules ──────────────────────────────────────────────────────────────

def pull_market_rules_from_sheet() -> list[dict]:
    ws = _market_worksheet()
    data = ws.get_all_values()
    rules = []
    for row in data[1:]:
        if len(row) < 2 or not row[0].strip() or not row[1].strip():
            continue
        rules.append({
            "market": row[0].strip(),
            "keyword": row[1].strip(),
            "active": (row[2].strip().lower() if len(row) > 2 else "1") not in ("0", "false", "no"),
            "sort_order": int(row[3]) if len(row) > 3 and str(row[3]).strip().isdigit() else 0,
        })
    return rules


def import_market_rules_from_sheet(db: Session) -> int:
    from models import MarketKeywordRule
    from classification import invalidate_rules_changed

    raw = pull_market_rules_from_sheet()
    if not raw:
        return 0
    db.query(MarketKeywordRule).delete()
    for i, r in enumerate(raw):
        db.add(MarketKeywordRule(
            market=r["market"],
            keyword=r["keyword"],
            active=r["active"],
            sort_order=r.get("sort_order", i),
        ))
    db.commit()
    invalidate_rules_changed(db)
    return len(raw)


def push_market_rules_to_sheet(db: Session) -> int:
    from models import MarketKeywordRule

    rules = (
        db.query(MarketKeywordRule)
        .order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id)
        .all()
    )
    rows = [["Thị trường", "Keyword", "Active (1/0)", "Sort"]]
    for r in rules:
        rows.append([r.market, r.keyword, "1" if r.active else "0", str(r.sort_order)])

    ws = _market_worksheet()
    ws.clear()
    ws.update(rows, "A1")
    return len(rules)


def sync_all_from_sheet(db: Session) -> dict:
    return {
        "market_imported": import_market_rules_from_sheet(db),
        "route_imported": import_route_rules_to_db(db),
    }


def sync_all_to_sheet(db: Session) -> dict:
    return {
        "market_pushed": push_market_rules_to_sheet(db),
        "route_pushed": push_route_rules_to_sheet(db),
    }
