# Market Research Hub — Tóm tắt cho Ban Giám đốc

**Là gì:** Nền tảng nghiên cứu thị trường & tình báo cạnh tranh tour du lịch. Tự động thu thập dữ liệu tour của **Vietravel + đối thủ** mỗi ngày, chuẩn hóa, rồi trả lời 3 câu hỏi: **Giá của ta đắt/rẻ hơn thị trường?** · **Tần suất khởi hành của ta theo kịp đối thủ?** · **Tuyến nào thị trường có mà ta chưa có?**

**Giá trị:** Thay công việc thu thập – đối chiếu thủ công trên Google Sheet bằng một quy trình tự động hằng ngày, có báo cáo cho BGĐ và cảnh báo cơ hội/rủi ro theo thời gian thực.

---

## Toàn cảnh hệ thống (1 bảng)

| Hạng mục | Nội dung |
|----------|----------|
| **Đối tượng dùng** | BGĐ (xem nhanh, đọc báo cáo) · Nhân viên nghiên cứu · Phát triển sản phẩm/Marketing · Quản trị viên vận hành |
| **Nguồn dữ liệu** | Vietravel · FindTourGo · các website đối thủ (plugin mở rộng) · nhập tay — hợp nhất về một mối |
| **Cập nhật** | Tự động **07:00 mỗi ngày**: cào → chuẩn hóa → phân loại → so sánh → chốt số liệu |
| **9 module chính** | (xem bảng dưới) |
| **3 trục so sánh** | **Giá** · **Tần suất khởi hành** · **Độ phủ tuyến** — luôn ưu tiên theo thứ tự này |
| **Đầu ra cho BGĐ** | Trang chủ KPI · Báo cáo CI (xem online / in / PDF / tải offline) · Cảnh báo cơ hội & rủi ro |
| **Chi phí vận hành** | Mục tiêu chi phí thấp (hạ tầng cloud gói cơ bản), vận hành tự động, ít cần can thiệp |

---

## 9 module & giá trị

| Module | BGĐ/Người dùng nhận được gì | Ai dùng chính |
|--------|------------------------------|---------------|
| **Trang chủ CI** | Bức tranh cạnh tranh trong 10 giây: chênh giá TB, số tuyến đắt/rẻ hơn TT, cảnh báo, cơ hội mùa lễ | BGĐ + nghiên cứu |
| **So sánh VTR** | So giá & tần suất ta vs đối thủ theo từng tuyến; chỉ ra tuyến "cần xử lý ngay" và "cơ hội tăng giá" | Nghiên cứu |
| **Market Lab** | Phát hiện **tuyến nên mở mới** (thị trường có nhu cầu, ta chưa khai thác) + theo dõi tuyến đang bán | Phát triển SP |
| **Sản phẩm & Data** | Kho dữ liệu tour để tra cứu, lọc, làm sạch & phân loại | Nghiên cứu |
| **Sự kiện & Lễ hội** | Cơ hội bán tour theo mùa lễ; lễ nào đối thủ phủ mà ta đang bỏ ngỏ; gợi ý marketing 12 tháng | Marketing + nghiên cứu |
| **Báo cáo BGĐ** | Báo cáo CI dựng lại từ dữ liệu mới nhất, in/PDF/offline; admin chỉnh sửa được như Word | BGĐ |
| **Vận hành** | Chạy/lập lịch thu thập dữ liệu, theo dõi tiến độ | Quản trị viên |
| **Quy tắc phân loại** | "Bộ não" tự phân loại & chuẩn hóa dữ liệu nhiều nguồn về một chuẩn | Quản trị viên |
| **Cài đặt** | Quản lý người dùng & phân quyền | Quản trị viên |

---

## Cách tính (đảm bảo công bằng & nhất quán)

- **So giá công bằng:** quy đổi giá thị trường về **cùng số ngày** của tour Vietravel, **cùng phân khúc**, **cùng giai đoạn khởi hành** rồi mới so.
- **Strict — "không khớp thì bỏ qua":** đối thủ phải có ngày khởi hành thật trùng thời điểm ta đang bán mới được đưa vào so sánh → **thà thiếu còn hơn sai**.
- **Một nguồn tính duy nhất** → con số trên Trang chủ, So sánh và Báo cáo **luôn khớp nhau**.
- **Chất lượng dữ liệu** được theo dõi liên tục (tỷ lệ phân loại đúng, tour thiếu giá/thiếu thông tin).

---

## Tình trạng & hướng tới
**Đang vận hành** đầy đủ 9 module với cập nhật tự động hằng ngày. **Hướng phát triển:** nâng cấp hạ tầng đặt tại VN để giảm độ trễ; bổ sung bộ lọc lễ hội vào các màn hình so sánh; tự động hóa thêm khâu gom dữ liệu đối thủ.
