"""Khớp rule tuyến nhanh — index theo keyword neo (dài nhất trong mỗi rule AND)."""
from __future__ import annotations

from collections import defaultdict


class RouteRuleMatcher:
    """
    Thay vì thử 600+ rule/tour, chỉ thử rule có keyword neo xuất hiện trong tên+lịch trình.
    Rule tuple: (rule_id, thi_truong, tuyen_tour, keywords...).
    """

    __slots__ = ("_rules", "_anchors")

    def __init__(self, rules: tuple[tuple[int, str, str, tuple[str, ...]], ...]):
        self._rules = rules
        by_anchor: dict[str, list[int]] = defaultdict(list)
        for i, (_rid, _mkt, _route, kws) in enumerate(rules):
            if not kws:
                continue
            anchor = max(kws, key=len)
            by_anchor[anchor].append(i)
        self._anchors = tuple(by_anchor.items())

    @classmethod
    def from_db_rules(cls, rules: tuple[tuple[int, str, str, tuple[str, ...]], ...]) -> RouteRuleMatcher:
        return cls(rules)

    def resolve(self, ten_tour: str, lich_trinh: str = "") -> tuple[str, str, bool, int | None]:
        combined = f"{ten_tour or ''} {lich_trinh or ''}".lower().strip()
        if not combined:
            return "", "", False, None

        candidates: set[int] = set()
        for anchor, indices in self._anchors:
            if anchor in combined:
                candidates.update(indices)
        if not candidates:
            return "", "", False, None

        for i in sorted(candidates):
            rule_id, mkt, route, kws = self._rules[i]
            if all(kw in combined for kw in kws):
                return mkt, route, True, rule_id
        return "", "", False, None

    def anchor_keywords(self) -> tuple[str, ...]:
        return tuple(anchor for anchor, _ in self._anchors)
