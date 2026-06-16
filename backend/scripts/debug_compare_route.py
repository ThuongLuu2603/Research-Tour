"""Soi data 1 tuyến để kiểm 'Giá TB VTR' + 'Rẻ nhất VTR' trong So sánh.

Chạy TRÊN VPS:
    cd /var/www/ota/backend && set -a && source .env && set +a
    venv/bin/python scripts/debug_compare_route.py Pattaya

In: tất cả tour VTR khớp keyword (giá / Dòng tour / có link / lịch KH), cấu hình
Dòng tour được tính (vtr tiers), và rẻ nhất VTR theo logic hiện tại.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KW = (sys.argv[1] if len(sys.argv) > 1 else "Pattaya")


def main() -> int:
    from compare_engine import _get_vtr_tiers, _norm_tier
    from database import SessionLocal
    from models import Tour

    tiers = _get_vtr_tiers()
    print(f"Dòng tour ĐƯỢC TÍNH giá VTR (cấu hình): {tiers or '(rỗng = lấy tất cả)'}\n")

    db = SessionLocal()
    try:
        q = (
            db.query(Tour)
            .filter(Tour.nguon == "Vietravel")
            .filter((Tour.tuyen_tour.ilike(f"%{KW}%")) | (Tour.ten_tour.ilike(f"%{KW}%")))
            .order_by(Tour.gia)
            .all()
        )
        print(f"VTR tour khớp '{KW}': {len(q)}\n")
        in_tier = []
        for t in q:
            dong = (t.dong_tour or "").strip()
            allowed = (not tiers) or (_norm_tier(dong) in tiers) or (not dong)
            has_link = bool((t.link_url or "").strip())
            mark = "✓tính" if allowed else "✗loại(tier)"
            print(f"  gia={int(t.gia or 0):>12,} | dong_tour={dong!r:<14} {mark} "
                  f"| link={'có' if has_link else 'KHÔNG'} | phan_khuc={t.phan_khuc!r}")
            print(f"        tuyen={t.tuyen_tour!r} diem_kh={t.diem_kh!r}")
            print(f"        ten={(t.ten_tour or '')[:65]!r}")
            print(f"        lich_kh={(t.lich_kh or '')[:60]!r}")
            if allowed:
                in_tier.append(t)

        print("\n--- RẺ NHẤT VTR (logic hiện tại) ---")
        if not in_tier:
            print("Không có tour nào trong tier → không tính được.")
        else:
            with_link = [t for t in in_tier if (t.link_url or "").strip()]
            pool = with_link if with_link else in_tier
            cheapest = min(pool, key=lambda x: x.gia or 0)
            abs_cheapest = min(in_tier, key=lambda x: x.gia or 0)
            print(f"Rẻ nhất (ưu tiên có link) = {int(cheapest.gia or 0):,}  ← đang hiển thị")
            print(f"Rẻ nhất TUYỆT ĐỐI (kể cả không link) = {int(abs_cheapest.gia or 0):,}")
            if cheapest.gia != abs_cheapest.gia:
                print("  ⚠️ KHÁC NHAU → do tour rẻ nhất KHÔNG có link nên bị bỏ qua.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
