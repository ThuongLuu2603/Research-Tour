"""Đồng bộ token keyword → rule_id cho lọc incremental."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from models import RouteKeywordRule, RouteRuleToken

logger = logging.getLogger(__name__)


def rebuild_route_rule_tokens(db: Session) -> int:
    db.query(RouteRuleToken).delete(synchronize_session=False)
    rules = db.query(RouteKeywordRule).filter(RouteKeywordRule.active == True).all()
    count = 0
    for r in rules:
        kws = [k.strip().lower() for k in (r.keywords or "").split(",") if k.strip()]
        if not kws:
            continue
        anchor = max(kws, key=len)
        for tok in {anchor, *kws}:
            if len(tok) < 2:
                continue
            db.add(RouteRuleToken(rule_id=r.id, token=tok[:128]))
            count += 1
    db.commit()
    logger.info("Rebuilt %s route_rule_tokens from %s rules", count, len(rules))
    return count
