"""Audit classification: tìm tour có thị trường/tuyến KHÔNG khớp Quy tắc phân loại.

Usage (chạy ở backend/ root, đã source .env):
    python -m scripts.audit_classification                 # in báo cáo tổng quan + sample
    python -m scripts.audit_classification --limit 100     # in tối đa 100 dòng mỗi nhóm
    python -m scripts.audit_classification --csv out.csv    # xuất full danh sách ra CSV

Phân loại mỗi tour canonical (Main/Vietravel) thành:
  - OK_MATCH    : rule match VÀ (thị trường, tuyến) khớp giá trị hiện tại
  - MISMATCH    : rule match NHƯNG rule cho giá trị KHÁC giá trị hiện tại
                  (tour đang sai → nên sửa theo rule)
  - ORPHAN      : rule KHÔNG match NHƯNG tour vẫn có thị trường/tuyến
                  (giá trị "mồ côi" — không rule nào back, vd lấy từ cột sheet sai
                   như "Trung Quốc Tân Cương" → "Châu Mỹ / Bờ Tây Mỹ")
  - OK_EMPTY    : rule không match VÀ tour cũng trống → đúng, chờ tạo rule
  - LOCKED      : manual_locked=True → admin set tay, BỎ QUA khỏi audit

READ-ONLY: script KHÔNG ghi gì vào DB.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _norm(s: str | None) -> str:
    return (s or "").strip()


def audit(limit: int, csv_path: str | None) -> int:
    from database import SessionLocal
    from models import Tour
    from data_sources import DB_CANONICAL_NGUON
    from classification import get_route_rule_matcher

    db = SessionLocal()
    try:
        matcher = get_route_rule_matcher()
        tours = (
            db.query(Tour)
            .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
            .all()
        )
        buckets: dict[str, list] = {
            "MISMATCH": [], "ORPHAN": [], "OK_MATCH": [], "OK_EMPTY": [], "LOCKED": [],
        }
        for t in tours:
            if getattr(t, "manual_locked", False):
                buckets["LOCKED"].append((t, "", ""))
                continue
            mk, rt, matched, _rid = matcher.resolve(t.ten_tour or "", t.lich_trinh or "")
            cur_mk, cur_rt = _norm(t.thi_truong), _norm(t.tuyen_tour)
            if matched:
                if _norm(mk) == cur_mk and _norm(rt) == cur_rt:
                    buckets["OK_MATCH"].append((t, mk, rt))
                else:
                    buckets["MISMATCH"].append((t, mk, rt))
            else:
                if cur_mk or cur_rt:
                    buckets["ORPHAN"].append((t, "", ""))
                else:
                    buckets["OK_EMPTY"].append((t, "", ""))

        total = len(tours)
        print("=" * 90)
        print(f"AUDIT CLASSIFICATION — {total} tour canonical (Main/Vietravel)")
        print("=" * 90)
        for k in ("MISMATCH", "ORPHAN", "OK_MATCH", "OK_EMPTY", "LOCKED"):
            print(f"  {k:10s}: {len(buckets[k]):6d}")
        print("-" * 90)
        print("  MISMATCH = tour SAI, rule cho giá trị khác → nên reclassify")
        print("  ORPHAN   = tour có giá trị nhưng KHÔNG rule nào match (vd lấy từ sheet sai)")
        print("=" * 90)

        def _dump(name: str, show_rule: bool) -> None:
            rows = buckets[name]
            if not rows:
                return
            print(f"\n### {name} ({len(rows)} tour) — hiển thị tối đa {limit}:")
            for t, mk, rt in rows[:limit]:
                cur = f"{_norm(t.thi_truong)!r}/{_norm(t.tuyen_tour)!r}"
                if show_rule:
                    print(f"  id={t.id} [{t.nguon}] {cur}  ── rule muốn → {mk!r}/{rt!r}")
                    print(f"      ten: {(t.ten_tour or '')[:90]!r}")
                else:
                    print(f"  id={t.id} [{t.nguon}] hiện={cur}")
                    print(f"      ten: {(t.ten_tour or '')[:90]!r}")
            if len(rows) > limit:
                print(f"  ... còn {len(rows) - limit} tour nữa (dùng --csv để xuất full)")

        _dump("MISMATCH", show_rule=True)
        _dump("ORPHAN", show_rule=False)

        if csv_path:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "bucket", "tour_id", "nguon", "ten_tour",
                    "cur_thi_truong", "cur_tuyen_tour",
                    "rule_thi_truong", "rule_tuyen_tour",
                ])
                for name in ("MISMATCH", "ORPHAN"):
                    for t, mk, rt in buckets[name]:
                        w.writerow([
                            name, t.id, t.nguon, (t.ten_tour or ""),
                            _norm(t.thi_truong), _norm(t.tuyen_tour), mk, rt,
                        ])
            print(f"\nĐã xuất MISMATCH + ORPHAN ra: {csv_path}")

        print("\nGỢI Ý:")
        print("  - Sửa MISMATCH + ORPHAN: chạy 'Apply Quy tắc phân loại' (full scan) trên UI.")
        print("    Tour match rule → sửa đúng. Tour ORPHAN không match → để TRỐNG (rule là")
        print("    nguồn chân lý) → vào panel 'Chưa khớp' để tạo rule mới.")
        return 0
    finally:
        db.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50, help="Số dòng tối đa in mỗi nhóm")
    ap.add_argument("--csv", type=str, default="", help="Đường dẫn file CSV xuất full")
    args = ap.parse_args(argv[1:])
    return audit(args.limit, args.csv or None)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
