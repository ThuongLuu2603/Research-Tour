"""Thay thế toàn bộ quy tắc tuyến tour trong DB (dùng cho import Excel/JSON)."""
from __future__ import annotations

from classification import invalidate_rules_changed
from classify_market_order import save_market_order
from models import RouteKeywordRule, Tour
from route_rule_tokens import rebuild_route_rule_tokens


def replace_route_rules(
    db,
    rules: list[dict],
    market_order: list[str] | None = None,
) -> dict:
    """Xóa route rules cũ, insert danh sách mới, cập nhật thứ tự thị trường + token index."""
    if not rules:
        raise ValueError("Danh sách quy tắc trống")

    old_count = db.query(RouteKeywordRule).count()
    db.query(Tour).filter(Tour.classification_rule_id.isnot(None)).update(
        {Tour.classification_rule_id: None},
        synchronize_session=False,
    )
    db.query(RouteKeywordRule).delete(synchronize_session=False)

    for row in rules:
        db.add(
            RouteKeywordRule(
                thi_truong=row["thi_truong"],
                tuyen_tour=row["tuyen_tour"],
                keywords=row["keywords"],
                sort_order=int(row.get("sort_order", 0)),
                active=bool(row.get("active", True)),
            )
        )
    db.commit()

    if market_order:
        save_market_order(db, market_order)

    token_count = rebuild_route_rule_tokens(db)
    invalidate_rules_changed(db)
    new_count = db.query(RouteKeywordRule).count()
    return {
        "old_count": old_count,
        "new_count": new_count,
        "token_count": token_count,
        "market_order": market_order or [],
    }
