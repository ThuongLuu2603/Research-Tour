"""Debug tour state — Issue #2: matcher correct but UI display wrong.

Usage (chạy ở backend/ root, DATABASE_URL prod):
    python -m scripts.debug_tour_state --name "Phú Quốc"
    python -m scripts.debug_tour_state --name "HCM - Phú Quốc"
    python -m scripts.debug_tour_state --id 1182139493864570881
    python -m scripts.debug_tour_state --id 1182139493864570881 --workspace 1

Mục đích: Phân biệt 4 nguyên nhân khả dĩ tour hiển thị sai:
  1. TourOverride trong workspace ghi đè wrong values.
  2. Tour.manual_locked = True → rule không re-apply.
  3. Tour.thi_truong/tuyen_tour cũ — chưa "Re-apply rules" sau khi sửa rule.
  4. ResearchGrid serializer merge logic bug.

Output: in canonical Tour, danh sách TourOverride theo workspace, và
effective display để user spot nguồn sai.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def _print_kv(label: str, value, indent: int = 2) -> None:
    pad = " " * indent
    print(f"{pad}{label:<26}: {value!r}")


def _fmt_id(v) -> str:
    # CRDB unique_rowid > 2^53 → in dạng str để chính xác.
    if v is None:
        return "None"
    return str(v)


def _query_tours(db, name: str | None, tour_id: int | None, limit: int):
    from sqlalchemy import or_, func
    from models import Tour

    q = db.query(Tour)
    if tour_id is not None:
        q = q.filter(Tour.id == tour_id)
        return q.all()
    if name:
        like = f"%{name.lower()}%"
        q = q.filter(or_(
            func.lower(Tour.ten_tour).like(like),
            func.lower(Tour.tuyen_tour).like(like),
        ))
        return q.order_by(Tour.id.desc()).limit(limit).all()
    return []


def _load_overrides_for_tour(db, tour_id: int):
    from models import TourOverride, Workspace

    rows = (
        db.query(TourOverride, Workspace)
        .outerjoin(Workspace, Workspace.id == TourOverride.workspace_id)
        .filter(TourOverride.tour_id == tour_id)
        .all()
    )
    return rows


def _load_rule(db, rule_id):
    if rule_id is None:
        return None
    from models import RouteKeywordRule

    return db.query(RouteKeywordRule).filter(RouteKeywordRule.id == rule_id).first()


def _print_tour(db, t, workspace_filter: int | None) -> None:
    _print_section(f"Tour id={_fmt_id(t.id)} — {t.ten_tour!r}")
    print(" [CANONICAL DB ROW]")
    _print_kv("id", _fmt_id(t.id))
    _print_kv("external_id", t.external_id)
    _print_kv("ten_tour", t.ten_tour)
    _print_kv("cong_ty", t.cong_ty)
    _print_kv("thi_truong (canonical)", t.thi_truong)
    _print_kv("tuyen_tour (canonical)", t.tuyen_tour)
    _print_kv("diem_kh", t.diem_kh)
    _print_kv("thoi_gian", t.thoi_gian)
    _print_kv("phan_khuc", t.phan_khuc)
    _print_kv("manual_locked", t.manual_locked)
    _print_kv("classification_rule_id", _fmt_id(t.classification_rule_id))
    _print_kv("classified_at", t.classified_at)
    _print_kv("nguon", t.nguon)
    _print_kv("sheet_source", t.sheet_source)
    _print_kv("festival_slug", t.festival_slug)
    _print_kv("province_code", t.province_code)
    _print_kv("flagged", t.flagged)
    _print_kv("updated_at", t.updated_at)
    _print_kv("last_synced_at", t.last_synced_at)

    rule = _load_rule(db, t.classification_rule_id)
    if rule is not None:
        print()
        print(" [LINKED RouteKeywordRule]")
        _print_kv("rule.id", _fmt_id(rule.id))
        _print_kv("rule.thi_truong", rule.thi_truong)
        _print_kv("rule.tuyen_tour", rule.tuyen_tour)
        _print_kv("rule.keywords", rule.keywords)
        _print_kv("rule.active", rule.active)
        _print_kv("rule.priority", rule.priority)
        if rule.thi_truong != t.thi_truong or rule.tuyen_tour != t.tuyen_tour:
            print("  >>> [MISMATCH] Rule khác với Tour canonical → cần Re-apply rules")
    else:
        if t.classification_rule_id is not None:
            print(f"  >>> [WARN] classification_rule_id={t.classification_rule_id} không tồn tại trong DB")

    print()
    print(" [TourOverride rows]")
    overrides = _load_overrides_for_tour(db, t.id)
    if workspace_filter is not None:
        overrides = [(o, w) for (o, w) in overrides if o.workspace_id == workspace_filter]
    if not overrides:
        print("  (không có override nào)")
    else:
        for ov, ws in overrides:
            print(f"  -- override id={_fmt_id(ov.id)} workspace_id={_fmt_id(ov.workspace_id)} "
                  f"name={(ws.name if ws else '?')!r} updated_at={ov.updated_at}")
            try:
                parsed = json.loads(ov.overrides_json or "{}")
            except Exception:
                parsed = {"_raw_": ov.overrides_json}
            for k, v in parsed.items():
                print(f"     {k:<22} = {v!r}")
            if any(k in parsed for k in ("thi_truong", "tuyen_tour")):
                print("     >>> Override có thi_truong/tuyen_tour → đây là nguồn UI hiển thị "
                      "trong workspace này.")

    # Effective merge — mô phỏng đúng cái UI thấy.
    print()
    print(" [EFFECTIVE DISPLAY per workspace] (canonical + override merge)")
    from tour_effective import merge_tour

    if not overrides:
        eff = merge_tour(t, None).to_dict()
        print(f"  -- workspace=(none): thi_truong={eff.get('thi_truong')!r} "
              f"tuyen_tour={eff.get('tuyen_tour')!r} has_override={eff.get('has_override')}")
    else:
        for ov, ws in overrides:
            eff = merge_tour(t, ov).to_dict()
            ws_lbl = f"id={_fmt_id(ov.workspace_id)} name={(ws.name if ws else '?')!r}"
            print(f"  -- workspace={ws_lbl}")
            print(f"     thi_truong (effective) = {eff.get('thi_truong')!r}")
            print(f"     tuyen_tour (effective) = {eff.get('tuyen_tour')!r}")
            print(f"     has_override           = {eff.get('has_override')}")

    # Diagnostic verdict.
    print()
    print(" [DIAGNOSTIC HINTS]")
    hits = []
    if overrides:
        for ov, _ws in overrides:
            try:
                parsed = json.loads(ov.overrides_json or "{}")
            except Exception:
                parsed = {}
            if parsed.get("thi_truong") or parsed.get("tuyen_tour"):
                hits.append(
                    f"Workspace #{_fmt_id(ov.workspace_id)} có TourOverride "
                    f"(thi_truong={parsed.get('thi_truong')!r}, tuyen_tour={parsed.get('tuyen_tour')!r}) "
                    "→ UI sẽ hiển thị giá trị này thay vì canonical."
                )
    if t.manual_locked:
        hits.append(
            "manual_locked=True → rule classification KHÔNG re-apply lên tour này. "
            "Nếu canonical sai, cần unlock rồi Re-apply rules."
        )
    if rule and (rule.thi_truong != t.thi_truong or rule.tuyen_tour != t.tuyen_tour):
        hits.append(
            f"Linked rule [{rule.thi_truong}/{rule.tuyen_tour}] KHÁC canonical "
            f"[{t.thi_truong}/{t.tuyen_tour}] → rule đã đổi sau khi tour được "
            "classify. Trigger Re-apply rules."
        )
    if t.classification_rule_id is None and (t.thi_truong or t.tuyen_tour):
        hits.append(
            "classification_rule_id=None nhưng vẫn có thi_truong/tuyen_tour → "
            "tour có thể được set thủ công, hoặc rule mới chưa apply. Re-apply rules."
        )
    if not hits:
        hits.append("Không phát hiện override/lock/mismatch — kiểm tra serializer "
                    "(EffectiveTour.to_dict) hoặc cache frontend (React Query stale).")
    for h in hits:
        print(f"  * {h}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug tour state — Issue #2")
    parser.add_argument("--name", type=str, default=None,
                        help="Match Tour.ten_tour HOẶC Tour.tuyen_tour (ILIKE %name%)")
    parser.add_argument("--id", type=str, default=None,
                        help="Match Tour.id (CRDB bigint OK)")
    parser.add_argument("--workspace", type=int, default=None,
                        help="Optional: chỉ show override của workspace_id này")
    parser.add_argument("--limit", type=int, default=5,
                        help="Khi search theo --name, số tour tối đa hiển thị (mặc định 5)")
    args = parser.parse_args()

    if not args.name and not args.id:
        parser.error("Phải truyền --name HOẶC --id")

    tour_id_int: int | None = None
    if args.id:
        try:
            tour_id_int = int(args.id)
        except ValueError:
            parser.error(f"--id phải là số nguyên: {args.id}")

    from database import SessionLocal

    db = SessionLocal()
    try:
        tours = _query_tours(db, args.name, tour_id_int, args.limit)
        if not tours:
            print("Không tìm thấy tour nào.")
            return 1
        print(f"Tìm thấy {len(tours)} tour matching.")
        for t in tours:
            _print_tour(db, t, args.workspace)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
