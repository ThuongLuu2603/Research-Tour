"""Khớp rule tuyến nhanh — index theo keyword neo (dài nhất trong mỗi rule AND)."""
from __future__ import annotations

import re
from collections import defaultdict

from text_fold import fold_vi


def _word_match(kw: str, text: str) -> bool:
    """
    Kiểm tra keyword xuất hiện như một *từ hoàn chỉnh* trong text (đã fold_vi).
    Tránh match giữa chừng: "my" KHÔNG được match trong "myanmar",
    nhưng "my" vẫn match trong "du lich my", "my dong tay", "my, nhat ban".

    Điều kiện biên:
    - Trước keyword: không phải chữ cái hoặc chữ số (a-z, 0-9)
    - Sau keyword: không phải chữ cái hoặc chữ số

    Ví dụ:
        "my"        in "du lich my"           → True   ✓
        "my"        in "du lich myanmar"       → False  ✓  (theo sau là "a")
        "my"        in "my nhat ban"           → True   ✓  (đầu chuỗi)
        "da nang"   in "da nang, hoi an"       → True   ✓
        "ha"        in "nha trang"             → False  ✓  (đứng trước là "n")
        "nha trang" in "nha trang bien xanh"   → True   ✓
    """
    return bool(re.search(
        r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])',
        text,
    ))


class RouteRuleMatcher:
    """
    Thay vì thử 700+ rule/tour, chỉ thử rule có keyword neo xuất hiện trong tên+lịch trình.
    So khớp trên bản đã bỏ dấu (côn đảo = con dao, my = mỹ).
    Dùng word-boundary check để tránh "my" khớp nhầm trong "myanmar".
    """

    __slots__ = ("_rules", "_anchors")

    def __init__(self, rules: tuple[tuple[int, str, str, tuple[str, ...]], ...]):
        folded_rules: list[tuple[int, str, str, tuple[str, ...]]] = []
        by_anchor: dict[str, list[int]] = defaultdict(list)
        for rid, mkt, route, kws in rules:
            fkws = tuple(fold_vi(k) for k in kws if k and str(k).strip())
            if not fkws:
                continue
            idx = len(folded_rules)
            folded_rules.append((rid, mkt.strip(), route.strip(), fkws))
            anchor = max(fkws, key=len)
            by_anchor[anchor].append(idx)
        self._rules = tuple(folded_rules)
        self._anchors = tuple(by_anchor.items())

    @classmethod
    def from_db_rules(cls, rules: tuple[tuple[int, str, str, tuple[str, ...]], ...]) -> RouteRuleMatcher:
        return cls(rules)

    def resolve(self, ten_tour: str, lich_trinh: str = "") -> tuple[str, str, bool, int | None]:
        combined = fold_vi(f"{ten_tour or ''} {lich_trinh or ''}")
        if not combined:
            return "", "", False, None

        # Bước 1: tìm candidates bằng substring (nhanh, có thể dư)
        candidates: set[int] = set()
        for anchor, indices in self._anchors:
            if anchor in combined:
                candidates.update(indices)
        if not candidates:
            return "", "", False, None

        # Bước 2: kiểm tra word-boundary cho tất cả keywords của rule
        for i in sorted(candidates):
            rule_id, mkt, route, kws = self._rules[i]
            if all(_word_match(kw, combined) for kw in kws):
                return mkt, route, True, rule_id
        return "", "", False, None

    def anchor_keywords(self) -> tuple[str, ...]:
        return tuple(anchor for anchor, _ in self._anchors)
