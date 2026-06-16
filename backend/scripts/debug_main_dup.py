"""Chẩn đoán: tour nhiều giá có bị gộp khi Main → DB không.

Chạy TRÊN VPS:
    cd /var/www/ota/backend && set -a && source .env && set +a
    venv/bin/python scripts/debug_main_dup.py MOSCOW

In ra:
  1. Các dòng trong TAB MAIN (Google Sheet) khớp keyword → xem Main có mấy dòng,
     mỗi dòng giá/link/mã tour gì (để biết QUERY có gộp trước khi vào Main không).
  2. external_id GỐC mỗi dòng → có trùng nhau không (trùng = sẽ tách theo giá+lịch).
  3. Các tour trong DB khớp keyword → xem DB hiện có mấy dòng.
"""
from __future__ import annotations

import sys

KW = (sys.argv[1] if len(sys.argv) > 1 else "MOSCOW").upper()


def main() -> int:
    import hashlib

    from sheets_tour_sync import _row_to_fields, _worksheet
    from tour_identity import compute_external_id

    # 1. TAB MAIN
    try:
        ws = _worksheet("Main")
        rows = ws.get_all_values()
    except Exception as e:  # noqa: BLE001
        print("Không đọc được tab Main:", e)
        return 1
    print(f"TAB MAIN: {len(rows)-1} dòng tổng. Tìm '{KW}':")
    hits = []
    for i, row in enumerate(rows[1:], start=2):
        joined = " ".join(str(c) for c in row).upper()
        if KW in joined:
            fields = _row_to_fields(row, nguon="Main")
            if not fields:
                print(f"  [dòng {i}] (bỏ qua — không parse được)")
                continue
            base = compute_external_id(
                "Main",
                ma_tour=fields.get("ma_tour", ""),
                link_url=fields.get("link_url", ""),
                ten_tour=fields.get("ten_tour", ""),
            )
            disc = hashlib.sha1(
                f"{fields.get('gia_raw','')}|{fields.get('lich_kh','')}".encode("utf-8")
            ).hexdigest()[:8]
            hits.append((i, fields, base, disc))
            print(f"  [dòng {i}] cong_ty={fields.get('cong_ty','')!r} gia={fields.get('gia_raw','')!r} "
                  f"ma_tour={fields.get('ma_tour','')!r} link={(fields.get('link_url','') or '')[:50]!r}")
            print(f"            ten={fields.get('ten_tour','')[:60]!r}")
            print(f"            base_id={base[-30:]!r}  disc(gia|lich)={disc}")

    bases = [h[2] for h in hits]
    print(f"\n=> {len(hits)} dòng khớp trong Main | base_id duy nhất: {len(set(bases))} "
          f"| {'CÓ TRÙNG → sẽ tách' if len(set(bases)) < len(bases) else 'KHÔNG trùng base'}")

    # 2. DB
    print("\n--- DB (tours khớp keyword) ---")
    try:
        from database import SessionLocal
        from models import Tour

        db = SessionLocal()
        try:
            q = db.query(Tour).filter(Tour.ten_tour.ilike(f"%{KW}%")).all()
            print(f"DB có {len(q)} tour khớp '{KW}':")
            for t in q:
                print(f"  id={t.id} nguon={t.nguon!r} cong_ty={t.cong_ty!r} gia={t.gia} "
                      f"ext={t.external_id!r}")
                print(f"      ten={(t.ten_tour or '')[:60]!r}")
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        print("Không query được DB:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
