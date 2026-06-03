"""Thứ tự nhóm thị trường cho route-first classification (kéo thả trên admin)."""
from __future__ import annotations

import json

from models import AppKv, RouteKeywordRule

MARKET_ORDER_KV_KEY = "classify_market_order"


def _markets_from_routes(rules: list[RouteKeywordRule]) -> list[str]:
    seen: dict[str, int] = {}
    for r in rules:
        mk = (r.thi_truong or "").strip()
        if not mk:
            continue
        if mk not in seen:
            seen[mk] = r.sort_order
        else:
            seen[mk] = min(seen[mk], r.sort_order)
    return sorted(seen.keys(), key=lambda m: (seen[m], m))


def get_saved_market_order(db) -> list[str]:
    row = db.get(AppKv, MARKET_ORDER_KV_KEY)
    if not row or not row.value_json:
        return []
    try:
        data = json.loads(row.value_json)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return []


def save_market_order(db, markets: list[str]) -> list[str]:
    clean = []
    seen: set[str] = set()
    for m in markets:
        mk = (m or "").strip()
        if mk and mk not in seen:
            clean.append(mk)
            seen.add(mk)
    row = db.get(AppKv, MARKET_ORDER_KV_KEY)
    if not row:
        row = AppKv(key=MARKET_ORDER_KV_KEY, value_json="[]")
        db.add(row)
    row.value_json = json.dumps(clean, ensure_ascii=False)
    db.commit()
    return clean


def merged_market_order(db, route_rules: list[RouteKeywordRule] | None = None) -> list[str]:
    """Thứ tự hiển thị + ưu tiên khớp: đã lưu trước, thị trường mới thêm cuối."""
    if route_rules is None:
        route_rules = (
            db.query(RouteKeywordRule)
            .filter(RouteKeywordRule.active == True)
            .all()
        )
    from_routes = _markets_from_routes(route_rules)
    saved = get_saved_market_order(db)
    out: list[str] = []
    seen: set[str] = set()
    for mk in saved:
        if mk in from_routes and mk not in seen:
            out.append(mk)
            seen.add(mk)
    for mk in from_routes:
        if mk not in seen:
            out.append(mk)
            seen.add(mk)
    return out


def market_rank_map(db, route_rules: list[RouteKeywordRule] | None = None) -> dict[str, int]:
    return {mk: i for i, mk in enumerate(merged_market_order(db, route_rules))}
