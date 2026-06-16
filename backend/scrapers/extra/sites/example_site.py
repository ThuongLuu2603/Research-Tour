"""SITE MẪU (template) — COPY file này để thêm 1 website tour mới.

HƯỚNG DẪN USER thêm 1 site:
  1. Copy file này → đặt tên mới, vd `dulichviet_site.py`.
  2. Đổi `key` (định danh duy nhất, không dấu cách — sẽ là giá trị cột "nguồn"
     trên Google Sheet) và `name` (tên hiển thị trên UI).
  3. Viết phần thân hàm `scrape(progress=None)`: cào web/API rồi trả về 1
     pandas.DataFrame theo ĐÚNG các cột chuẩn bên dưới (STANDARD_COLUMNS).
     - Gọi `progress(pct, msg)` (nếu khác None) để cập nhật thanh tiến trình.
     - KHÔNG cần cột "nguon" — sheet_writer tự gán = key.
  4. Lưu file. Site tự xuất hiện ở "Vận hành" (auto-register). Không sửa file nào khác.

Khung này trả DataFrame RỖNG (đúng cột) — chạy được ngay nhưng không ghi tour nào.
"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from scrapers.extra.registry import ExtraScraper, register

# Cột chuẩn — TRÙNG với output findtourgo `_item_to_row` (trừ cột "nguon" do writer gán).
# Giữ đúng tên + thứ tự để sheet_writer map sang tab chung nhất quán.
STANDARD_COLUMNS = [
    "cong_ty",      # Tên công ty / đối thủ
    "thi_truong",   # Thị trường (vd "Trung Quốc") — để "" nếu chưa phân loại
    "tuyen_tour",   # Tuyến tour — để "" nếu chưa phân loại
    "ten_tour",     # Tên tour
    "lich_trinh",   # Lịch trình (điểm đến) — có thể để ""
    "diem_kh",      # Điểm khởi hành
    "thoi_gian",    # Thời gian (vd "5 ngày" / "5N4Đ")
    "gia",          # Giá (chuỗi số VND, vd "9.990.000")
    "lich_kh",      # Lịch khởi hành (các ngày dd/mm/yyyy)
    "link_url",     # URL tour (link thô)
    "ma_tour",      # Mã tour (định danh tour của site đó)
    "khach_san",    # Khách sạn — có thể để ""
    "hang_khong",   # Hàng không — có thể để ""
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=STANDARD_COLUMNS)


def scrape(progress: Callable[[int, str], None] | None = None) -> pd.DataFrame:
    """Cào tour từ site. TRẢ pandas.DataFrame theo STANDARD_COLUMNS.

    User thay phần thân: gọi requests/BeautifulSoup/API…, build list[dict], rồi
    `return pd.DataFrame(rows, columns=STANDARD_COLUMNS)`.
    """
    if progress:
        progress(10, "Site mẫu — chưa cào gì (template)")
    # TODO(user): cào dữ liệu thật ở đây.
    df = _empty_df()
    if progress:
        progress(100, f"Site mẫu xong: {len(df)} tour")
    return df


register(ExtraScraper(
    key="example",
    name="Site mẫu (template)",
    scrape=scrape,
))
