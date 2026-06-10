"""Debug classification rule matching for a single tour.

Usage (chạy ở backend/ root):
    python -m scripts.debug_classify "Tour HCM - Phú Quốc 3 ngày 2 đêm: Lặn ngắm san hô"
    python -m scripts.debug_classify "Tour name" "Lich trinh ngay 1...ngay 2..."

Mục đích: phục vụ Issue #2 — vì sao tour HCM - Phú Quốc lại bị classify
sang Bangkok - Pattaya / Thái Lan. Script in ra:
  1. Folded text combined (tên + lịch trình)
  2. Anchor candidates (rule có anchor xuất hiện trong text)
  3. Với mỗi candidate: tất cả keyword AND có pass _word_match không
  4. Rule winner (rule đầu tiên pass cả AND-set) — chính là kết quả thật
  5. Top 5 priority/non-priority rules để dễ phát hiện bad rule data

Chạy script này trên prod database (DATABASE_URL env) để lấy bộ rule
hiện hành, KHÔNG dùng bundle JSON (rule DB có thể đã bị user sửa).
"""
from __future__ import annotations

import os
import sys

# Cho phép import backend modules khi chạy từ root project
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from text_fold import fold_vi  # noqa: E402
from route_rule_matcher import _word_match  # noqa: E402


def _load_rules_from_db() -> list[tuple[int, str, str, tuple[str, ...], bool, int]]:
    """Trả về danh sách rule (id, thi_truong, tuyen_tour, kws_folded, priority, sort_order).

    Sort theo logic giống _load_route_rules: priority trước, rồi market_rank, rồi
    số keyword nhiều hơn, rồi sort_order, rồi id.
    """
    from database import SessionLocal
    from models import RouteKeywordRule
    from classify_market_order import market_rank_map

    db = SessionLocal()
    try:
        rows = (
            db.query(RouteKeywordRule)
            .filter(RouteKeywordRule.active == True)  # noqa: E712
            .all()
        )
        ranks = market_rank_map(db, rows)

        def _row_key(r: RouteKeywordRule) -> tuple:
            kws = tuple(k.strip().lower() for k in (r.keywords or "").split(",") if k.strip())
            mk = (r.thi_truong or "").strip()
            if getattr(r, "priority", False):
                return (0, 0, -len(kws), r.sort_order, r.id)
            return (1, ranks.get(mk, 99999), -len(kws), r.sort_order, r.id)

        sorted_rows = sorted(rows, key=_row_key)
        out: list[tuple[int, str, str, tuple[str, ...], bool, int]] = []
        for r in sorted_rows:
            raw_kws = tuple(k.strip().lower() for k in (r.keywords or "").split(",") if k.strip())
            if not raw_kws:
                continue
            folded_kws = tuple(fold_vi(k) for k in raw_kws if k.strip())
            if not folded_kws:
                continue
            out.append((
                r.id,
                (r.thi_truong or "").strip(),
                (r.tuyen_tour or "").strip(),
                folded_kws,
                bool(getattr(r, "priority", False)),
                int(r.sort_order or 0),
            ))
        return out
    finally:
        db.close()


def _check_rule(combined: str, kws: tuple[str, ...]) -> tuple[bool, list[tuple[str, bool]]]:
    """Trả về (all_pass, per_keyword [(kw, passed_word_match)])."""
    results = [(kw, _word_match(kw, combined)) for kw in kws]
    return all(p for _, p in results), results


def debug_classify(ten_tour: str, lich_trinh: str = "") -> None:
    combined = fold_vi(f"{ten_tour or ''} {lich_trinh or ''}")
    print("=" * 80)
    print(f"TEN TOUR: {ten_tour!r}")
    print(f"LICH TRINH: {(lich_trinh[:200] + '...') if len(lich_trinh) > 200 else lich_trinh!r}")
    print(f"FOLDED COMBINED: {combined!r}")
    print("=" * 80)

    rules = _load_rules_from_db()
    print(f"\nTotal active rules in DB: {len(rules)}")

    # Step 1: anchor substring match
    candidates: list[tuple[int, int, str, str, tuple[str, ...], bool]] = []
    for idx, (rid, mk, route, kws, prio, _so) in enumerate(rules):
        anchor = max(kws, key=len)
        if anchor in combined:
            candidates.append((idx, rid, mk, route, kws, prio))

    print(f"\nStep 1 — Anchor substring candidates: {len(candidates)}")
    for idx, rid, mk, route, kws, prio in candidates[:50]:
        anchor = max(kws, key=len)
        tag = "[PRIO]" if prio else "      "
        print(f"  {tag} rule_id={rid} order_idx={idx} anchor={anchor!r} -> {mk!r} / {route!r} kws={kws}")
    if len(candidates) > 50:
        print(f"  ... ({len(candidates) - 50} more)")

    # Step 2: word boundary verification (logic thực tế của matcher)
    print(f"\nStep 2 — Word-boundary verification (matcher walks candidates in order):")
    winner = None
    for idx, rid, mk, route, kws, prio in candidates:
        all_pass, per_kw = _check_rule(combined, kws)
        tag = "[PRIO]" if prio else "      "
        verdict = "MATCH" if all_pass else "skip "
        print(f"  {tag} {verdict} rule_id={rid} -> {mk!r} / {route!r}")
        for kw, ok in per_kw:
            mark = "OK" if ok else "NO"
            print(f"          [{mark}] kw={kw!r}")
        if all_pass and winner is None:
            winner = (rid, mk, route, kws, prio)
            # KHÔNG break — vẫn in các candidate sau để debug.

    print("\n" + "=" * 80)
    if winner:
        rid, mk, route, kws, prio = winner
        print(f"WINNER: rule_id={rid} thi_truong={mk!r} tuyen_tour={route!r}")
        print(f"        priority={prio}  keywords={kws}")
    else:
        print("WINNER: (none) — tour KHÔNG khớp rule nào → thị trường/tuyến để trống.")
    print("=" * 80)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    ten_tour = argv[1]
    lich_trinh = argv[2] if len(argv) > 2 else ""
    debug_classify(ten_tour, lich_trinh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
