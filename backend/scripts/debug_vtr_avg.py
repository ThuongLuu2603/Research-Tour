"""In TỪNG BƯỚC cách tính 'Giá TB VTR' cho 1 tuyến (mặc định Bangkok-Pattaya / HCM).

Chạy TRÊN VPS:
    cd /var/www/ota/backend && set -a && source .env && set +a
    venv/bin/python scripts/debug_vtr_avg.py

Dùng ĐÚNG hàm của compare_engine (build_segment_stats + SegmentStats) nên số ra
khớp 100% với module So sánh.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROUTE_KW = "Bangkok - Pattaya"
DEPART_KW = "Hồ Chí Minh"


def main() -> int:
    from compare_engine import (
        _departure_weights,
        build_segment_stats,
        vtr_period_label,
    )
    from database import SessionLocal
    from models import Tour

    db = SessionLocal()
    try:
        tours = db.query(Tour).filter(Tour.thi_truong == "Thái Lan").all()
    finally:
        db.close()

    segments = build_segment_stats(tours)
    seg = None
    for s in segments:
        if ROUTE_KW.lower() in (s.tuyen_tour or "").lower() and DEPART_KW.lower() in (s.diem_kh or "").lower():
            seg = s
            break
    if seg is None:
        print("Không tìm thấy segment phù hợp. Các segment Thái Lan có:")
        for s in segments:
            print(f"  tuyen={s.tuyen_tour!r} diem_kh={s.diem_kh!r} | vtr={len(s.vtr_entries)}")
        return 1

    print(f"SEGMENT: thị trường={seg.thi_truong!r} | tuyến={seg.tuyen_tour!r} | điểm KH={seg.diem_kh!r}")
    period_dates = seg._vtr_period_dates()
    print(f"Giai đoạn VTR: {vtr_period_label(period_dates)}  ({len(period_dates)} ngày KH gộp)")

    entries = seg.vtr_price_entries
    weights = _departure_weights(entries, period_dates, in_vtr_period=True)
    print(f"\nTour VTR dùng tính giá (đã lọc Dòng tour cấu hình): {len(entries)}")
    print(f"{'giá':>12} {'ngày':>5} {'đoàn(w)':>8} {'giá×w':>16} {'ngày×w':>9}  dòng_tour | tên")
    sum_gia_w = sum_ngay_w = sum_w = 0.0
    for e, w in sorted(zip(entries, weights), key=lambda x: x[0].gia):
        gw = e.gia * w
        nw = e.so_ngay * w
        sum_gia_w += gw
        sum_ngay_w += nw
        sum_w += w
        print(f"{int(e.gia):>12,} {e.so_ngay:>5} {w:>8.1f} {int(gw):>16,} {nw:>9.1f}  "
              f"{e.dong_tour!r:<10} {(e.ten_tour or '')[:40]!r}")

    print(f"\nΣ(giá×đoàn)      = {int(sum_gia_w):,}")
    print(f"Σ(số_ngày×đoàn)  = {sum_ngay_w:.1f}")
    print(f"Σ(đoàn)          = {sum_w:.1f}")

    avg_day = seg.vietravel_avg_day
    avg_days = seg.vtr_avg_days
    avg_price = seg.vtr_avg_price
    print("\n--- KẾT QUẢ (khớp module So sánh) ---")
    print(f"Giá TB/ngày = Σ(giá×đoàn)/Σ(ngày×đoàn) = {int(sum_gia_w):,}/{sum_ngay_w:.1f} = "
          f"{int(avg_day) if avg_day else None:,}")
    print(f"Số ngày TB  = Σ(ngày×đoàn)/Σ(đoàn)     = {sum_ngay_w:.1f}/{sum_w:.1f} = {avg_days}")
    print(f"GIÁ TB VTR  = Giá TB/ngày × Số ngày TB = {int(avg_price) if avg_price else None:,}")
    print(f"\n(So sánh: trung bình CỘNG đơn thuần = {int(sum(e.gia for e in entries)/len(entries)):,} "
          f"— KHÁC, vì không trọng số/không chuẩn hoá ngày)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
