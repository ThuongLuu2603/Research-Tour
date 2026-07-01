# PRD — Market Research Hub (Vietravel Competitive Intelligence)

> **Product Requirements Document**
> Nền tảng Nghiên cứu Thị trường & Tình báo Cạnh tranh tour du lịch — Vietravel
> Phiên bản: 1.0 · Ngày: 2026-06-19 · Phạm vi: Chức năng · Quy trình · Hệ thống · Vận hành
> *Tài liệu mô tả ở mức sản phẩm/nghiệp vụ, không đi sâu vào code.*

---

## 1. Tổng quan sản phẩm

### 1.1. Bối cảnh & Vấn đề
Phòng nghiên cứu thị trường và Ban Giám đốc (BGĐ) của Vietravel cần biết **sản phẩm tour của Vietravel (VTR) đang đứng ở đâu so với đối thủ** về giá, tần suất khởi hành và độ phủ tuyến. Dữ liệu đối thủ nằm rải rác trên hàng chục website tour (mỗi nơi một cấu trúc, một cách đặt tên, một định dạng lịch khởi hành), được nhập tay vào Google Sheet — rất tốn công, dễ sai, không so sánh được theo thời gian thực, và không có cái nhìn tổng hợp để ra quyết định.

### 1.2. Tầm nhìn sản phẩm
**Market Research Hub** là một nền tảng duy nhất hợp nhất dữ liệu tour của Vietravel với dữ liệu thị trường/đối thủ, **tự động chuẩn hóa & phân loại**, rồi cung cấp các năng lực phân tích cạnh tranh (so sánh giá, so sánh tần suất, phát hiện khoảng trống tuyến, cơ hội theo mùa lễ hội) và **báo cáo cho BGĐ** — biến công việc thu thập – đối chiếu thủ công thành một quy trình tự động hằng ngày.

### 1.3. Mục tiêu sản phẩm (Goals)
| # | Mục tiêu | Chỉ số thành công (gợi ý) |
|---|----------|---------------------------|
| G1 | Tự động thu thập & hợp nhất dữ liệu tour VTR + thị trường mỗi ngày | Chuỗi cập nhật tự động chạy ổn định 07:00 hằng ngày |
| G2 | So sánh giá/tần suất VTR vs thị trường theo từng tuyến một cách công bằng | 100% tuyến "so sánh được" có chênh giá %, gap tần suất |
| G3 | Phát hiện cơ hội (khoảng trống tuyến, cơ hội mùa lễ, cơ hội tăng giá) | Danh sách cơ hội xếp hạng tự động, có hành động gợi ý |
| G4 | Cung cấp báo cáo CI cho BGĐ xem nhanh & xuất offline | Báo cáo HTML/PDF dựng lại từ dữ liệu mới nhất |
| G5 | Đảm bảo chất lượng dữ liệu (phân loại đúng, loại dữ liệu bẩn) | % tour phân loại OK theo dõi được; dữ liệu bẩn bị loại khỏi thống kê |
| G6 | Vận hành chi phí thấp, ổn định trên hạ tầng cloud | Chuỗi job có khóa chống chồng, tự dọn job treo |

### 1.4. Đối tượng người dùng (Personas / Roles)
| Persona | Vai trò hệ thống | Nhu cầu chính |
|---------|------------------|---------------|
| **Ban Giám đốc (BGĐ)** | `analyst` (xem) | Xem nhanh bức tranh cạnh tranh; đọc báo cáo CI; nắm KPI & cảnh báo |
| **Nhân viên nghiên cứu thị trường** | `analyst` | So sánh giá/tần suất theo tuyến; tìm cơ hội; làm sạch & phân loại dữ liệu; xuất CSV |
| **Nhân viên phát triển sản phẩm / Marketing** | `analyst` | Tìm tuyến nên mở mới; lập kế hoạch tour theo mùa lễ |
| **Quản trị viên / Vận hành (Admin)** | `admin` | Chạy & lập lịch scraper; quản lý quy tắc phân loại; quản lý người dùng; chỉnh báo cáo |

### 1.5. Phạm vi
**Trong phạm vi (In scope):** thu thập dữ liệu tour đa nguồn, chuẩn hóa & phân loại tự động, các module phân tích cạnh tranh, module lễ hội, báo cáo BGĐ, quản trị quy tắc, quản trị vận hành, quản lý người dùng & workspace.

**Ngoài phạm vi (Out of scope):** bán tour/đặt chỗ (không phải hệ thống booking), quản lý khách hàng/CRM, thanh toán, dữ liệu nội bộ doanh thu/lợi nhuận thực tế của VTR.

---

## 2. Thuật ngữ & Khái niệm nghiệp vụ (Glossary)

> Đây là phần nền tảng — mọi module đều dùng chung các định nghĩa này. Thống nhất khái niệm là điều kiện để các con số khớp nhau giữa các màn hình.

| Thuật ngữ | Định nghĩa |
|-----------|-----------|
| **Nhóm so sánh / Segment** | Đơn vị so sánh chuẩn = **Thị trường + Tuyến tour + Điểm khởi hành**. Gộp mọi sản phẩm/thời gian trên cùng tuyến. Chỉ tuyến mà **cả VTR và thị trường đều có sản phẩm** mới "so sánh được". |
| **Tuyến tour** | Một hành trình cụ thể trong một thị trường (vd thị trường "Mỹ" → tuyến "Bờ Đông"). |
| **Thị trường** | Vùng/quốc gia điểm đến (Nhật Bản, Hàn Quốc, Châu Âu, nội địa…). |
| **Điểm khởi hành (Điểm KH)** | Nơi xuất phát tour: HCM, Hà Nội, Đà Nẵng… |
| **Số đoàn / Tần suất khởi hành** | Số chuyến khởi hành/tháng/sản phẩm, ước tính từ **Lịch khởi hành** (`lich_kh`). Đồng thời là **trọng số** cho mọi phép tính trung bình giá. |
| **Giá so sánh (comparison price)** | Giá thị trường **quy đổi về cùng số ngày của VTR** = (giá trung bình/ngày của thị trường) × (số ngày trung bình VTR). Mục đích: so công bằng giữa các tour khác độ dài. |
| **Chênh % (gap %)** | = Giá TB tour VTR ÷ Giá so sánh − 1. Âm = VTR **rẻ hơn** thị trường; dương = VTR **đắt hơn**. |
| **Gap tần suất (vs trung bình)** | Chênh số đoàn của VTR so với **một đối thủ trung bình** trên tuyến (≥ ±20% = dẫn/kém). |
| **Phân khúc giá** | Standard / Premium / Luxury — gán **tương đối** so với giá TB/ngày thị trường cùng nhóm (≥1.30 = Luxury, ≤0.70 = Standard). Áp dụng cho tour đối thủ. |
| **Dòng tour** | Phân khúc nội bộ của VTR (Tiết kiệm / Giá Tốt / Tiêu chuẩn / Cao cấp / ESG…), lấy trực tiếp từ dữ liệu VTR. |
| **Phủ sóng / Coverage** | Trạng thái mỗi ô (Thị trường × Tuyến): **Cả hai** / **Chỉ VTR** / **Chỉ thị trường**. |
| **Khoảng trống / White space** | Tuyến thị trường đang có nhu cầu (đủ số sản phẩm/đoàn) nhưng VTR **chưa khai thác**. |
| **Opportunity score** | Điểm cơ hội = (đoàn thị trường/tháng) × (số đối thủ) — đại diện cho nhu cầu đã được thị trường kiểm chứng. |
| **Phase (giai đoạn tuyến)** | Trạng thái động của một tuyến: *Mở rộng / Cạnh tranh giá / Thắt cung / Áp lực lịch / Ổn định*. |
| **Insight** | Phát hiện tự động có mức ưu tiên (Giá > Tần suất > Phủ sóng > Chất lượng dữ liệu), kèm link sâu tới đúng nhóm so sánh. |
| **Alert / Cảnh báo** | Thông báo lưu lại (vd chênh giá TB biến động mạnh so với hôm qua). |
| **Gắn lễ (festival tag)** | Tour có ngày khởi hành rơi trong **±3 ngày** quanh một lễ hội. |
| **Gap score (lễ)** | Mức độ đối thủ phủ một lễ nhiều hơn VTR → cơ hội VTR đang bỏ ngỏ. |
| **Workspace** | Không gian làm việc lưu các chỉnh sửa phân loại của người dùng, tách biệt với dữ liệu chung. |

---

## 3. Nguyên tắc sản phẩm (Product Principles)

Bốn nguyên tắc xuyên suốt, định hình mọi tính năng:

1. **Ưu tiên Giá → Tần suất → Phủ sóng.** Khi sinh insight/cảnh báo, giá luôn được ưu tiên trước, rồi đến tần suất khởi hành, rồi đến độ phủ tuyến.
2. **Quy tắc (Rule) là nguồn sự thật duy nhất.** Mọi phân loại (thị trường/tuyến), chuẩn hóa (công ty/điểm KH/thời gian/lịch) và mọi tùy chọn trong dropdown đều bắt nguồn từ bảng Quy tắc do admin quản lý — không dùng dữ liệu phân loại sai/cũ.
3. **"Không khớp thì bỏ qua" (strict matching).** Tour không parse được ngày khởi hành, hoặc đối thủ không có ngày khởi hành thật trùng giai đoạn VTR đang bán → **bị loại khỏi mọi thống kê** giá/tần suất/phủ sóng. Thà thiếu còn hơn sai.
4. **Một nguồn tính cho mọi màn hình.** KPI tổng được tính từ một engine duy nhất → Trang chủ, So sánh VTR và Báo cáo BGĐ **luôn khớp số**.

---

## 4. Kiến trúc thông tin (Information Architecture)

```
Vietravel · Market Research Hub
│
├── NHÓM CHÍNH (mọi người dùng đã đăng nhập)
│   ├── Trang chủ CI            /            Bản tin tình báo hằng ngày (KPI, insight, cảnh báo)
│   ├── So sánh VTR             /compare     6 tab: Tổng quan · Giá · Tần suất · Đối thủ · Phủ sóng · Ghép SP
│   ├── Market Lab              /market-lab  Cơ hội & vận hành theo Tuyến/Thị trường
│   ├── Sản phẩm & Data         /data        Bảng dữ liệu gốc + chỉnh sửa phân loại (Workspace)
│   ├── Sự kiện & Lễ hội        /festivals   8 tab: lịch lễ, coverage gap, pricing, forecast, marketing…
│   └── Báo cáo BGĐ             /reports     2 báo cáo: Báo cáo CI + So sánh đối thủ (lưu HTML, rebuild hằng ngày)
│
└── NHÓM QUẢN TRỊ (chỉ Admin)
    ├── Vận hành                /ops         Scraper Hub — chạy/lập lịch scraper, đồng bộ Sheet, theo dõi job
    ├── Quy tắc phân loại       /rules       8 nhóm quy tắc (gồm tab Báo cáo) + đồng bộ Google Sheet
    └── Cài đặt                 /settings    Hồ sơ cá nhân + quản lý người dùng

Ngoài layout: /login (đăng nhập)
```

---

## 5. Yêu cầu chức năng (Functional Requirements)

### 5.1. Trang chủ CI — Intelligence Hub (`/`)
**Mục đích:** Màn hình mở đầu — bản tin tình báo hằng ngày cho cả BGĐ và nhân viên nghiên cứu.

**Chức năng:**
- **Tóm tắt 1 dòng** tự sinh (vd: "Chênh giá TB +X% · N tuyến đắt hơn TT · M tuyến thiếu lịch KH").
- **6 KPI card** bấm được (deep-link sang trang con), mỗi card có "delta vs hôm qua": Chênh giá TB %, số tuyến Đắt hơn TT, Rẻ hơn TT, số Nhóm so sánh, Tần suất dẫn/kém, số tour Chưa phân loại.
- **Insight hôm nay**: danh sách insight tự động nhóm theo loại (Giá/Tần suất/Phủ sóng/Chất lượng), có mức độ (critical/warning/info) và link tới đúng nhóm so sánh.
- **Cảnh báo** có badge số chưa đọc.
- **Bảng chất lượng dữ liệu**: % phân loại OK, số tour thiếu giá / thiếu điểm KH / bị gắn cờ / tổng tour VTR.
- **Biểu đồ xu hướng 14 ngày** (chênh giá TB %, số nhóm đắt/rẻ).
- **Khối "Lễ hội sắp tới — cơ hội phủ tour"**: top lễ mà đối thủ phủ nhiều hơn VTR, link sang trang Lễ hội.

### 5.2. So sánh VTR (`/compare`) — Module lõi
**Mục đích:** So sánh trực diện VTR vs thị trường trên cùng nhóm (Thị trường · Tuyến · Điểm KH · Thời gian) về giá, tần suất và độ phủ.

**Bộ lọc dùng chung:** Thị trường → Tuyến tour → Điểm khởi hành (dropdown phân tầng, khởi tạo được từ URL). Có **4 preset 1 chạm**: "Cần xử lý (đắt nhất)", "Cơ hội tăng giá", "Khoảng trống", "Đối thủ nặng ký".

**6 tab con:**
| Tab | Chức năng chính | Đầu ra |
|-----|-----------------|--------|
| **Tổng quan** | Phân bổ vị thế giá; khối "Cần xử lý ngay" top-3 tuyến đắt hơn TT ≥10% | Donut, danh sách ưu tiên |
| **So sánh giá** | Bảng segment (Giá TB VTR, rẻ nhất VTR + link, Giá thị trường, Giá so sánh, Chênh %); sort, lọc nhanh đắt/rẻ/ngang, tìm kiếm, **watchlist** | Bảng, scatter giá, grouped bar, **popup chi tiết segment** + mini-chart lịch sử 30 ngày, **xuất CSV** |
| **Tần suất KH** | So đoàn/tháng VTR vs đối thủ TB; phân bổ theo thứ trong tuần | Bar gap, scatter, drill-down 1 tuyến |
| **Đối thủ** | Xếp hạng "đối thủ nặng ký" theo **Score 0–100** (gia quyền: nhóm trùng 35% + tần suất 30% + số chương trình 15% + giá cạnh tranh 20%); so song song tối đa 4 đối thủ | Bảng xếp hạng, panel chi tiết đối thủ, xuất CSV |
| **Phủ sóng** | Ma trận độ phủ theo thị trường; bảng **white-space** sort theo điểm cơ hội | Cột chồng, **bubble cơ hội**, popup tuyến, xuất CSV |
| **Ghép SP** | Ghép cặp 1-1 một sản phẩm VTR với các tour đối thủ tương đương (cùng thị trường + cùng tuyến) để so kè trực tiếp giá, giá/ngày, chênh % và tần suất | Panel trái chọn tuyến/SP VTR + bảng ứng viên đối thủ (xem chi tiết dưới) |

**Chi tiết tab Ghép SP (bố cục 2 vùng):**
- **Panel trái — "Tuyến VTR":** danh mục tour VTR gom 2 cấp — theo **đầu khởi hành** (🛫) → theo **tuyến**. Mỗi tuyến chỉ hiện **1 dòng đại diện** (SP rẻ nhất) kèm "Giá từ … · N SP" (N đếm **dedup theo chương trình**, không theo dòng giá). Sắp xếp: đầu KH/tuyến nhiều SP lên trước.
- **Lọc 1 tuyến:** click một tuyến → ẩn các tuyến khác, **bung đầy đủ các SP** của tuyến đó (tên · giá · số ngày · link) + nút **"Xem tất cả tuyến ✕"** để bỏ lọc. Click một SP cụ thể → nạp tour đó vào panel phải.
- **Panel phải — kết quả ghép:** thẻ tóm tắt tour VTR (thị trường · tuyến · điểm KH · thời gian · giá · giá/ngày · TS khởi hành dạng khoảng · link) + **bảng "Tour đối thủ gợi ý"** sắp theo công ty, các cột: **Điểm khớp %** · Công ty · Tên tour · **Đầu KH** · Giá · **Giá TB/ngày** · **Chênh %** · **TS khởi hành (khoảng min–max đoàn/tháng)** · Link.
- **Quy tắc ghép cặp:** gate cứng **phải cùng thị trường và cùng tuyến** (thiếu/khác → loại); điểm khớp = độ giống tuyến 40% + điểm KH 25% + số ngày 20% + giá 15%; chỉ giữ ứng viên ≥ 0.35; mặc định top 8 (xem §6.4).

**Phụ trợ:** Panel **"Giá trị chưa khớp alias"** — liệt kê Công ty/Điểm KH/Thời gian của tour VTR chưa khớp quy tắc, gợi ý bổ sung tại trang Quy tắc.

### 5.3. Market Lab (`/market-lab`)
**Mục đích:** Phân tích động lực cung–cầu theo **Tuyến/Thị trường** — phát hiện cơ hội mở sản phẩm mới và theo dõi vận hành tuyến đang khai thác.

**Chức năng:**
- Chuyển **grain** Tuyến tour ↔ Thị trường; 2 tab: **Cơ hội** (tuyến nên mở SP/tăng lịch) vs **Vận hành VTR** (tuyến VTR đang có SP); lọc theo ngưỡng "Score ≥"; toggle ẩn tuyến nghi sai thị trường.
- **Triển vọng tuần này** — top tuyến cần chú ý + gợi ý hành động.
- Bảng tuyến: Đoàn TT, Đoàn VTR, Chênh giá %, Gap tần suất, **Phase**, **Opportunity score** (có công thức tooltip).
- **Heat Map (treemap)** thị trường theo đoàn/tháng, drill-down.
- Panel chi tiết tuyến: **lịch chiến lược cung theo tháng** (bar VTR vs TT), **xu hướng 30 ngày** (cung & chênh giá), link sang So sánh giá / Phủ sóng.

### 5.4. Sản phẩm & Data — Research Grid (`/data`)
**Mục đích:** Bảng dữ liệu gốc toàn bộ tour để tra cứu, lọc, **chỉnh sửa phân loại** và xuất.

**Chức năng:**
- **Bộ lọc:** tìm kiếm; chip Nguồn; multi-select Thị trường → Tuyến (phân tầng), Điểm KH, Công ty, Phân khúc; toggle "Flagged"; sort mọi cột; phân trang 50/trang.
- **Chỉnh sửa inline (theo Workspace):** sửa cặp Thị trường+Tuyến, Điểm KH, Thời gian, ghi chú; **chỉ chọn từ option chuẩn của Quy tắc** (không cho nhập tự do); gắn cờ Flag; **chỉnh sửa hàng loạt** (bulk). Có badge "đã chỉnh bởi admin / workspace".
- **Workspace:** mỗi user có 1 workspace cá nhân; **chia sẻ** cho user khác với quyền Xem/Copy/Sửa; **copy override** từ workspace khác; quản lý thành viên.
- Cột **TB tần suất đoàn/tháng** tính từ lịch KH. Admin có nút **"Refresh rules"** (áp lại phân loại toàn bộ). **Xuất CSV.**

### 5.5. Sự kiện & Lễ hội (`/festivals`)
**Mục đích:** Lịch lễ hội Việt Nam + đối chiếu với tour, tìm cơ hội phủ tour theo mùa lễ.

**8 tab (nhóm Tổng quan / Khám phá / Phân tích / Hành động):**
1. **Tổng quan** — KPI lễ 30/90 ngày, tour gắn lễ, tỷ lệ VTR cover; 3 thẻ cảnh báo thông minh; điểm chất lượng dữ liệu.
2. **Lịch & Timeline** — xem timeline/calendar; lọc Vùng/Loại lễ/Khoảng ngày + tìm tên.
3. **Lễ Tết (âm lịch)** — lễ âm lịch tự tính, planner nhiều năm.
4. **Coverage Gap** — bảng lễ đối thủ cover nhưng VTR thiếu (gap score); **gợi ý mapping tự động** + tạo nhanh quy tắc gán lễ.
5. **Pricing Premium** — % chênh giá tour gắn lễ vs không gắn lễ.
6. **Heatmap tỉnh** — độ phủ lễ↔tour theo vùng/tỉnh, đánh dấu tỉnh under-served.
7. **Demand Forecast** — dự báo nhu cầu 6 tháng, khuyến nghị tồn kho (high/medium/low) theo mật độ lễ.
8. **Marketing** — lịch marketing 12 tháng, gợi ý tour + campaign theo lễ.

**Hành động admin:** Refresh scrape · Seed lễ âm · Re-tag tour. **Popup chi tiết lễ** (gộp theo công ty, VTR đầu danh sách).

### 5.6. Báo cáo BGĐ (`/reports`)
**Mục đích:** Báo cáo trình bày cho Ban Giám đốc. Module có **2 báo cáo song song** (chuyển bằng tab):

| Báo cáo | Nội dung |
|---------|----------|
| **Báo cáo CI** | Báo cáo cạnh tranh tổng hợp: Tóm tắt điều hành + "Cần hành động"; dải KPI; trend 14 ngày; **I.** Phân tích giá (VTR đắt/rẻ hơn TT) · **II.** Tần suất khởi hành · **III.** Phủ sóng (khoảng trống) · **IV.** Insight tự động · **V.** Lễ hội — cơ hội phủ tour |
| **So sánh đối thủ** | Báo cáo so sánh 1:1 theo mẫu BP, bố cục **Đầu khởi hành → Thị trường → từng Tuyến**. Mỗi thị trường là bảng **3 cột**: VTR · Đối thủ (công ty mạnh nhất từng tuyến) · Ngang tầm (Saigontourist), với 4 dòng tiêu chí: **Sản phẩm** (số SP·đoàn) · **Giá bán** (giá từ + SP rẻ nhất + link) · **Tần suất KH** (theo tháng, từ hiện tại trở đi) · **Nhận định** (ô nhập tay). Có thanh nhảy nhanh theo đầu KH + nút "↑ Lên đầu" |

**Chức năng người dùng:**
- **Xem nhanh:** báo cáo được **lưu sẵn nguyên khối HTML**, mở trang không tính lại → tải nhanh (Báo cáo CI lưu ở cache đĩa; So sánh đối thủ lưu trong hệ thống key-value).
- **Tự dựng lại hằng ngày:** sau khi chốt snapshot ngày, hệ thống tự rebuild & lưu sẵn cả 2 báo cáo.
- **Làm mới (thủ công):** dựng lại từ dữ liệu mới nhất. *(Với So sánh đối thủ, "Làm mới" sẽ xóa các chỉnh sửa tay theo đầu KH.)*
- **In/PDF** và **Tải HTML offline** (theo tab đang xem).
- **Sửa trực tiếp** (chỉ admin/super_admin) bằng trình soạn thảo như Word: Báo cáo CI sửa toàn bộ; So sánh đối thủ sửa **theo từng đầu khởi hành** (chọn từ dropdown — vì báo cáo lớn, tách nhỏ để soạn mượt). Bản sửa tay được **giữ lại khi rebuild tự động**.

**Cấu hình phạm vi báo cáo:** báo cáo So sánh đối thủ lọc theo **đầu khởi hành + thị trường** được tick chọn ở tab **"Báo cáo"** trong module Quy tắc phân loại (để trống = lấy tất cả). Chỉ tour có đầu KH khớp alias chuẩn mới được đưa vào.

**Vai trò:** mọi user xem/in/tải; chỉ admin sửa nội dung & lưu cấu hình phạm vi.

### 5.7. Vận hành — Scraper Hub (`/ops`) · *Admin*
**Mục đích:** Trung tâm vận hành thu thập & đồng bộ dữ liệu thị trường.
**Chức năng:**
- **Trạng thái dữ liệu hệ thống:** tổng số tour + breakdown theo nguồn (Main/Vietravel/FindTourGo…) so với ngưỡng kỳ vọng (badge xanh/vàng), cảnh báo nếu tab Main thiếu dữ liệu.
- **Đồng bộ Sheet Main → DB** (nút chính, có thanh tiến độ).
- **Chạy scraper từng nguồn:** Vietravel (chạy ngay → ghi DB rồi xuất tab Sheet; kèm nút phụ **"Sync từ Sheet → DB"** kéo bản sửa tay tab Vietravel về DB) · FindTourGo (chạy ngay → ghi tab Sheet) · **các website đối thủ khác** (bật/tắt tham gia chuỗi auto, chạy ngay riêng).
- **Lập lịch tự động:** đặt **giờ chạy bước 1** (giờ VN); các bước sau **tự nối tiếp** khi bước trước xong. Bảng 6 bước: Scrape Vietravel → Scrape FindTourGo → Scrape site khác → Sync Main → DB → Tag tour theo lễ → Snapshot BGĐ. Hiển thị lần chạy gần nhất mỗi bước.
- **Quản lý job (Job History):** bảng phân trang (trạng thái, tour mới/cập nhật/tổng, thời gian, ghi chú); theo dõi tiến độ real-time; phát hiện **job treo** → nút **"Dừng"** từng job + **"Dọn job treo"**; tự dọn khi mở trang. (Chi tiết kỹ thuật ở §8 Vận hành.)

### 5.8. Quy tắc phân loại (`/rules`) · *Admin*
**Mục đích:** Quản lý toàn bộ quy tắc tự động phân loại/chuẩn hóa — nguồn sự thật cho mọi dropdown & mọi phép tính. Tiêu đề: "Quy tắc phân loại & Key matching".
**8 nhóm quy tắc (tab):**
1. **Tuyến tour** — keyword → Thị trường + Tuyến (có cờ ưu tiên), kèm panel "Chưa khớp" kéo-thả & cảnh báo xung đột keyword.
2. **Công ty** — alias → tên chuẩn.
3. **Điểm khởi hành** — alias → điểm KH chuẩn.
4. **Thời gian** — text → số ngày chuẩn.
5. **Định dạng Ngày KH** — DSL parse lịch khởi hành (có nút test định dạng).
6. **Lễ hội** — map địa điểm lễ → Thị trường/Tuyến (gán festival cho tour).
7. **So sánh VTR ↔ Thị trường** — chọn dòng tour VTR & phân khúc thị trường nào được đưa vào so sánh giá.
8. **Báo cáo** *(mới)* — tick chọn **đầu khởi hành + thị trường** được đưa vào báo cáo **So sánh đối thủ** (giới hạn phạm vi báo cáo; xem §5.6). Lưu cấu hình → hệ thống tự dựng lại bản lưu báo cáo.

**Chức năng chung:** thanh trạng thái (% phân loại OK, số chưa phân loại, số rule, tổng "chưa khớp"); thêm/sửa/xóa quy tắc; seed mặc định; **đồng bộ 2 chiều với Google Sheet**; panel **"Chưa khớp"** với gợi ý tự động + xem tour mẫu + gán nhanh; **áp dụng quy tắc lên toàn bộ tour** (job nền có tiến độ) + nút re-apply riêng từng nhóm.

### 5.9. Cài đặt (`/settings`)
**Chức năng:** sửa hồ sơ (tên hiển thị, avatar), đổi mật khẩu. **Admin:** danh sách user, tạo user (role analyst/admin), đổi role, reset mật khẩu, khóa/mở khóa, xem lần đăng nhập cuối.

### 5.10. Đăng nhập (`/login`)
Đăng nhập bằng username/password (JWT). Hết phiên/401 → tự đẩy về login.

---

## 6. Năng lực phân tích & Phương pháp tính (Methodology)

> Đây là phần "linh hồn" của sản phẩm. Các định nghĩa tính toán dưới đây là **yêu cầu nghiệp vụ** (không phải chi tiết code) và phải nhất quán trên mọi màn hình.

### 6.1. Danh mục năng lực phân tích
1. **So sánh giá** VTR vs thị trường theo nhóm tuyến (đắt/rẻ %, quy đổi cùng số ngày & cùng phân khúc).
2. **So sánh tần suất khởi hành** (đoàn/tháng; dẫn/kém so đối thủ TB và đối thủ mạnh nhất).
3. **Phủ sóng** + phát hiện khoảng trống cơ hội.
4. **Market Lab theo tuyến**: opportunity score, phase, momentum, dự báo tuần, lịch cung, cảnh báo.
5. **Profile đối thủ** + **ghép cặp tour 1-1**.
6. **Phân khúc giá tương đối** toàn thị trường.
7. **Phân tích thị trường tổng** (theo thị trường/công ty/tuyến).
8. **Insight & Alert tự động** + Trang chủ KPI + trend.
9. **Báo cáo BGĐ** (in/PDF/offline).
10. **Module lễ hội**: pricing premium, demand forecast, marketing calendar, heatmap, coverage gap, lunar planner.
11. **Phân loại tự động** + kiểm chất lượng phân loại.
12. **Snapshot lịch sử hằng ngày** → trend & momentum.

### 6.2. Công thức cốt lõi
- **Số ngày TB VTR** = Σ(số đoàn × số ngày) ÷ Σ(số đoàn).
- **Giá TB/ngày** = Σ(giá tour × số đoàn) ÷ Σ(số đoàn × số ngày). *(Trọng số là số đoàn, không phải trung bình cộng đơn thuần.)*
- **Giá so sánh** = Giá TB/ngày thị trường × Số ngày TB VTR.
- **Chênh %** = Giá TB tour VTR ÷ Giá so sánh − 1.
- **Robust average:** khi biên độ giá lớn (có luxury), cắt 10% hai đầu + dùng median để chống nhiễu.

### 6.3. Quy tắc tính toán bắt buộc
1. **Matching theo NGÀY + ĐỊA ĐIỂM (strict):** đối thủ chỉ được tính nếu có ngày khởi hành thật rơi đúng vào giai đoạn VTR đang bán trên tuyến. Tour không parse được ngày → loại khỏi giá/tần suất/phủ sóng.
2. **Dedup sản phẩm theo GIÁ:** khóa trùng = Công ty | mã/link/tên | **giá**. Các biến thể "tách dòng theo giá" của cùng một chương trình **không bị gộp** (giữ mức rẻ nhất, không tính sai trung bình).
3. **Đếm "Sản phẩm VTR" theo chương trình** (dedup mã tour), không theo dòng giá.
4. **Quy đổi cùng số ngày** trước khi so giá.
5. **Phân khúc tương đối** theo nhóm; VTR loại trừ (dùng Dòng tour).
6. **Ngưỡng nghiệp vụ thống nhất:** giá ±5% (rẻ/đắt), tần suất ±20% (dẫn/kém); sanity giá ≤300tr/tour, ≤50tr/ngày, độ dài 0.5–45 ngày.
7. **Một nguồn tính cho KPI** → các module luôn khớp số.

### 6.4. Cách xếp hạng cơ hội & đối thủ
- **Opportunity score (tuyến)** = đoàn thị trường/tháng × số đối thủ.
- **White space:** VTR chưa có SP nhưng thị trường ≥3 sản phẩm / ≥8 đoàn/tháng.
- **Phase tuyến:** Mở rộng (cung ↑≥12%) · Cạnh tranh giá (giá ↓≤−3%) · Thắt cung (cung ↓≤−10%) · Áp lực lịch (gap tần suất ≤−25%) · Ổn định.
- **Score đối thủ (0–100):** nhóm trùng VTR 35% + tần suất 30% + số chương trình 15% + giá cạnh tranh 20%.
- **Ghép cặp tour 1-1 (matcher, tab Ghép SP):** gate cứng — chỉ ghép tour đối thủ **cùng thị trường + cùng tuyến** với tour VTR (thiếu/khác → loại); điểm khớp = độ giống tuyến 40% + điểm KH 25% + số ngày 20% + giá 15%; giữ ứng viên có điểm ≥ 0.35, sắp theo điểm rồi theo chênh giá, mặc định top 8.
- **Premium % (lễ):** chênh giá median tour gắn lễ vs không gắn lễ trên cùng tuyến.

---

## 7. Quy trình nghiệp vụ (Business Processes)

### 7.1. Luồng dữ liệu end-to-end (Data Pipeline)
```
NGUỒN                          THU THẬP                         CHUẨN HÓA & PHÂN TÍCH
─────────────────────────────────────────────────────────────────────────────────────
travel.com.vn (API) ─► Vietravel scraper ─────────────► DB (nguon=Vietravel) ─► export tab Sheet VTR
findtourgo (API) ────► FindTourGo scraper ─► tab Sheet FindTourGo ─(Sheet tự merge)─┐
5 site extra ────────► Extra scrapers ─────► tab Sheet chung (per-source)            │
analyst nhập tay ──────────────────────────────────────────────────► tab Main ◄─────┘
                                                                          │
                       tab Main ──(Sync Main → DB)──► DB (nguon=Main)
                                                                          │
   ┌──────────────────────────────────────────────────────────────────────────────┐
   │ sanitize (loại text rác) → parse giá/ngày → resolve alias (công ty/điểm KH/    │
   │ thời gian) → phân loại Thị trường/Tuyến (rule) → phân khúc giá → tag lễ hội     │
   └──────────────────────────────────────────────────────────────────────────────┘
                                                                          │
   DB ─► So sánh VTR · Phủ sóng · Market Lab · Lễ hội · Insight · Báo cáo BGĐ
        └─► Snapshot hằng ngày (KPI tổng / segment / tuyến) → trend & momentum
```

### 7.2. Các bước chuẩn hóa khi nạp dữ liệu
1. **Sanitize:** loại token rác (`nan/none/null`…) để không làm sai thống kê.
2. **Parse giá & số ngày:** giá < 10.000đ hoặc ≤ 0 → loại khỏi thống kê; số ngày chặn 0–45.
3. **Resolve alias:** chuẩn hóa tên công ty / điểm khởi hành / thời gian.
4. **Phân loại Thị trường + Tuyến** theo Quy tắc (rule là nguồn chân lý; không khớp → để trống "Chưa khớp").
5. **Phân khúc giá** (đối thủ) / lấy **Dòng tour** (VTR).
6. **Tag lễ hội** (±3 ngày quanh ngày lễ).
7. **Snapshot** chốt số liệu ngày.

**Cơ chế an toàn dữ liệu (Sticky fields):** nếu một lần scrape trả về rỗng cho một trường, hệ thống **giữ giá trị cũ** thay vì xóa — chống mất dữ liệu quý do lỗi cào nhất thời. Đồng thời chỉ xóa hàng loạt (prune) khi nguồn trả về đủ tối thiểu số dòng (chống xóa nhầm khi nguồn lỗi/trống).

### 7.3. User journeys tiêu biểu
1. **Brief sáng (BGĐ/analyst):** Trang chủ CI → đọc tóm tắt + KPI → bấm "Đắt hơn TT" → So sánh giá lọc sẵn → mở popup segment → xuất CSV.
2. **Định giá cạnh tranh:** So sánh VTR → chọn Thị trường/Tuyến → tab Giá → sort theo Chênh % → xem tour rẻ nhất đối thủ (link) → thêm watchlist.
3. **Phát triển sản phẩm:** Market Lab tab Cơ hội → lọc Score cao → chọn tuyến white-space → xem lịch cung theo tháng → sang Phủ sóng xác nhận khoảng trống.
4. **Cơ hội mùa lễ:** Trang chủ (khối lễ) → Festivals Coverage Gap → lễ gap cao chưa có rule → tạo mapping rule → re-tag → tab Marketing lấy gợi ý tour + campaign.
5. **Làm sạch dữ liệu:** Sản phẩm & Data → lọc tour chưa phân loại/flagged → sửa theo option chuẩn → lưu workspace; admin bổ sung alias ở Quy tắc → áp dụng rule lên tour.
6. **Vận hành dữ liệu (admin):** Vận hành → chạy/lập lịch scraper → theo dõi job → đồng bộ Sheet → snapshot.
7. **Báo cáo BGĐ:** Reports → Làm mới → Sửa trực tiếp → In/PDF hoặc Tải HTML offline gửi BGĐ.

---

## 8. Vận hành hệ thống (Operations)

### 8.1. Nguồn dữ liệu
| Nguồn | Cơ chế | Lưu vào | Vai trò |
|-------|--------|---------|---------|
| **Vietravel** (travel.com.vn) | API JSON | DB (canonical) + tab Sheet VTR | Dữ liệu "nhà" để so sánh |
| **FindTourGo** | API JSON (aggregator nhiều quốc gia) | Google Sheet → merge sang tab Main | Thị trường & đối thủ tổng hợp |
| **Các site extra** (plugin) | Scrape HTML / API riêng từng site | 1 tab Sheet chung (per-source) | Mở rộng đối thủ ngách |
| **Nhập tay (analyst)** | Nhập trực tiếp trên Google Sheet (tab Main) | tab Main → DB | Bổ sung/hiệu chỉnh thủ công |

> Kiến trúc plugin cho extra sites: thêm một website đối thủ mới = thêm một module nhỏ độc lập, không sửa phần còn lại; một site lỗi không làm hỏng các site khác hay cả hệ thống.

### 8.2. Lập lịch & tự động hóa
- **Chuỗi cập nhật hằng ngày — 07:00 (giờ VN):** Scrape Vietravel → Scrape FindTourGo → Scrape các site extra (đang bật) → Đồng bộ Main → DB → Cập nhật lễ hội + Tag tour theo lễ → Chụp snapshot BGĐ → **dựng lại & lưu sẵn báo cáo** (CI + So sánh đối thủ). Mỗi bước **chờ bước trước xong**; **một bước lỗi không chặn các bước sau**.
- **Cron tick từ bên ngoài (mỗi 10–15 phút):** đánh thức service (chống "ngủ đông" trên hạ tầng free), giữ ấm cache, và chạy các job đã đến giờ.
- **Snapshot hằng ngày** cũng được chụp sau mỗi lần scrape thủ công.

### 8.3. Quản lý job
- **Trạng thái job:** pending → running → success/failed, kèm % tiến độ, số tour mới/cập nhật, heartbeat, người kích hoạt. Theo dõi real-time tại Scraper Hub.
- **Khóa chống chạy chồng (single-flight lock):** chỉ một job được ghi dữ liệu tour tại một thời điểm — tránh xung đột trên môi trường cloud nhiều tiến trình. Khóa **tự hết hạn** nếu job chết (chống treo).
- **Hủy job (cooperative cancel):** dừng sớm giữa các lô, giải phóng khóa, ngừng tốn tài nguyên.
- **Dọn job treo (zombie reaper):** tự đánh dấu thất bại các job không còn tiến trình thật (theo heartbeat/thời lượng); khi service khởi động lại, mọi job "running" mồ côi được đóng và nhả khóa.

### 8.4. Đồng bộ Google Sheet (phụ thuộc quan trọng)
Google Sheet vừa là **nguồn nhập tay**, vừa là **kho quy tắc**, vừa là **lớp trung gian** và **kênh hiển thị**:
- **Tab Main:** nguồn chuẩn gom FindTourGo + chỉnh sửa tay → đồng bộ vào DB.
- **Tab Vietravel:** DB ghi ra để hiển thị; có thể sync ngược nếu sửa tay.
- **Tab FindTourGo / Extra:** scraper ghi vào, sau đó merge sang Main.
- **Tab quy tắc (route/market):** đồng bộ **2 chiều** với hệ thống.
- Xác thực bằng Google Service Account (không phải đăng nhập Google của người dùng).

### 8.5. Kiểm soát chất lượng dữ liệu
- Giá < 10.000đ hoặc ≤ 0 → loại khỏi tính toán (vẫn hiển thị).
- Sticky fields giữ giá trị cũ khi scrape rỗng; ngưỡng tối thiểu trước khi prune.
- Rule là nguồn chân lý → không khớp thì để trống (vào panel "Chưa khớp").
- **Khóa thủ công (manual lock):** khi admin sửa, rule/sheet không ghi đè nữa (cho đến khi tên tour đổi = tour mới).
- **Bảng chỉ số chất lượng:** tổng tour, số chưa phân loại, thiếu giá, thiếu điểm KH, bị gắn cờ, % phân loại OK, 5 lần scrape gần nhất.

### 8.6. Công việc vận hành của Admin
| Công việc | Tần suất | Cách thực hiện |
|-----------|----------|----------------|
| Chuỗi scrape + sync + snapshot | Hằng ngày 07:00 (tự động) | Scheduler |
| Ping cron (chống ngủ đông + catch-up) | Mỗi 10–15 phút | Cron ngoài |
| Cấu hình giờ chạy / bật-tắt site | Khi cần | Scraper Hub |
| Chạy scrape thủ công | Ad-hoc | Scraper Hub |
| Hủy/dọn job treo | Khi gặp | Scraper Hub |
| Quản rule + gán alias "Chưa khớp" + áp rule | Khi có tour mới chưa phân loại | Quy tắc phân loại |
| Làm mới & chỉnh báo cáo BGĐ | Định kỳ / khi cần | Báo cáo BGĐ |

---

## 9. Hệ thống & Kiến trúc (System Architecture)

### 9.1. Sơ đồ thành phần
```
Người dùng (trình duyệt)
        │ HTTPS
        ▼
Web Service (cloud) ───────────────────────────────────────
  • Frontend (SPA React) — phục vụ tĩnh
  • Backend API (FastAPI)
  • Scheduler nền (chuỗi cập nhật hằng ngày)
        │            │              │                 │
        ▼            ▼              ▼                 ▼
   Database     Cache (Redis      Google Sheets    Cron ngoài
  (CockroachDB   + disk + RAM)    (Service Acct)   (đánh thức +
   Serverless)                                      catch-up)
```

### 9.2. Công nghệ
- **Frontend:** React + TypeScript + Vite, React Router, TanStack React Query, Tailwind, Recharts (biểu đồ), TinyMCE (soạn báo cáo).
- **Backend:** Python (FastAPI), SQLAlchemy, APScheduler (lập lịch), gspread + Google Service Account (Sheets), pandas (xuất CSV/Excel).
- **Database:** CockroachDB Serverless (tương thích PostgreSQL); có tìm kiếm toàn văn.
- **Hạ tầng:** Web Service trên cloud (gói free), cache đa tầng (Redis + đĩa + bộ nhớ), cron ngoài để đánh thức. *(Có kế hoạch dự phòng migrate sang VPS đặt tại VN + tự host PostgreSQL để giảm độ trễ và hết hiện tượng cold start.)*

### 9.3. Caching (vì hiệu năng & chi phí)
Các tính toán nặng (so sánh ~hàng nghìn tour, Market Lab, Trang chủ, báo cáo, insight lễ hội) được **cache nhiều tầng** (bộ nhớ → Redis → đĩa) với cơ chế *stale-while-revalidate*: trả ngay bản đã lưu rồi dựng lại ở nền → người dùng không phải chờ. Cache tự làm mới theo "vân tay dữ liệu" (số lượng + thời điểm cập nhật mới nhất), không làm mới định kỳ vô ích.

---

## 10. Mô hình dữ liệu (Data Model — mức khái niệm)

| Nhóm | Thực thể | Mục đích |
|------|----------|----------|
| **Lõi** | **Tour** | Mỗi dòng = 1 sản phẩm tour (VTR hoặc đối thủ); lưu cả dữ liệu thô + suy diễn (phân loại, phân khúc, gắn lễ) |
| | **ScrapeJob** | Lịch sử & tiến độ mỗi lần chạy scraper/sync |
| | **DailySnapshot / SegmentSnapshot / RouteDailyMetrics** | Chốt KPI tổng / theo segment / theo tuyến mỗi ngày → trend & Market Lab |
| **Quy tắc** | MarketKeywordRule, RouteKeywordRule, Company/Departure/Duration/ScheduleAlias, DateFormatRule, FestivalTourMappingRule | Bộ quy tắc chuẩn hóa & phân loại — nguồn sự thật |
| **Lễ hội** | **Festival** + **FestivalTourMapping** (bảng nối tour↔lễ, M-N) | Lịch lễ hội + gắn tour vào lễ |
| **Người dùng** | **User, Workspace, WorkspaceMember, TourOverride, SavedView** | Tài khoản, không gian làm việc, chỉnh sửa riêng theo workspace, lưu bộ lọc |
| **Hệ thống** | IntelAlert, AppKv, JobLock | Cảnh báo CI, key-value chung, khóa job |

**Quan hệ chính:** Tour ↔ ScrapeJob (nguồn job); Tour ↔ RouteKeywordRule (quy tắc phân loại đã áp); Tour ↔ Festival (qua bảng nối, nhiều-nhiều); Workspace ↔ TourOverride ↔ Tour (chỉnh sửa riêng); User ↔ Workspace (sở hữu & chia sẻ).

> Đặc thù: phần lớn liên kết dữ liệu là **khớp văn bản mềm** (theo keyword/tên), phản ánh bản chất tổng hợp dữ liệu từ nhiều nguồn không chuẩn — không phải khóa ngoại cứng.

---

## 11. Phân quyền & Bảo mật

- **Đăng nhập:** username/password, cấp **JWT** (phiên 24h). *Không* có đăng nhập bằng Google (Google chỉ dùng cho Sheets).
- **2 vai trò:** `analyst` (mặc định) và `admin` (cấp cao nhất).
- **Bảo vệ:** mọi trang cần đăng nhập; nhóm menu & API quản trị chỉ dành cho admin; hết phiên/401 → đẩy về login.
- **Đặc quyền admin:** quản lý quy tắc & áp rule, vận hành scraper, quản lý người dùng, sửa nội dung báo cáo. Khi admin sửa trường phân loại lõi → **ghi thẳng dữ liệu chung + khóa**; analyst sửa → chỉ vào **override workspace** riêng.
- **Mô hình Workspace:** quyền chia sẻ 3 cấp **Xem < Copy < Sửa**; chủ workspace/admin mới được chia sẻ/thu hồi.
- **Cron** được bảo vệ bằng secret riêng (không phải JWT).
- **Điểm cần củng cố (ghi nhận):** đảm bảo đặt `SECRET_KEY` và `CRON_SECRET` qua biến môi trường (tránh giá trị mặc định); chưa có refresh-token thực.

---

## 12. Yêu cầu phi chức năng (NFR)

| Nhóm | Yêu cầu |
|------|---------|
| **Hiệu năng** | Cache đa tầng + precompute snapshot; nén GZip; tách bundle FE; index DB chuyên dụng; tính toán nặng dựng nền (người dùng không chờ). |
| **Chống cold start** | Ping ngoài đánh thức service; health-check trả 200 tức thì; khởi tạo DB ở luồng nền. |
| **Độ tin cậy** | Khóa job cấp DB + heartbeat (chống chạy chồng & treo); retry quanh thao tác DB; tự dọn job mồ côi khi khởi động lại; chuỗi tuần tự, một bước lỗi không chặn bước sau; đồng bộ idempotent (không ghi thừa). |
| **Bảo mật** | JWT + bcrypt; RBAC admin/analyst; CORS allow-list; secret cho cron. |
| **Chi phí** | Mục tiêu chi phí thấp (gói free); tiết kiệm tài nguyên DB (chỉ tải cột cần, tránh truy vấn nặng, hủy job dừng sớm). |
| **Khả năng mở rộng nguồn** | Thêm website đối thủ qua plugin độc lập, không sửa phần lõi. |
| **Tính nhất quán số liệu** | KPI tính từ một engine duy nhất → các màn hình luôn khớp. |

---

## 13. Tích hợp & Phụ thuộc bên ngoài

| Phụ thuộc | Vai trò | Rủi ro & xử lý |
|-----------|---------|----------------|
| **API Vietravel** | Nguồn dữ liệu VTR | Site đổi sang SPA → dùng API JSON; log chi tiết khi token/endpoint đổi |
| **API FindTourGo** | Nguồn dữ liệu thị trường | Lọc chỉ giá VND để không sai giá |
| **Các website extra** | Nguồn đối thủ ngách | Plugin độc lập; một site lỗi không ảnh hưởng phần còn lại |
| **Google Sheets** | Nhập tay + kho rule + trung gian merge | Service Account; ngưỡng tối thiểu chống xóa nhầm |
| **Nguồn lễ hội VN + lịch âm** | Dữ liệu lễ hội | Scrape định kỳ + tự tính lễ âm lịch |
| **Cron ngoài** | Đánh thức service + catch-up | Bảo vệ bằng secret |

---

## 14. Rủi ro vận hành đã được xử lý

1. **Cold start (hạ tầng free):** cron đánh thức + giữ ấm cache.
2. **Website đổi cấu trúc:** chuyển sang API JSON; scraper không "chết cứng", trả những gì lấy được + cảnh báo rõ.
3. **Hai job tranh chấp ghi dữ liệu:** khóa lease cấp DB, tự hết hạn.
4. **Job treo do service restart:** tự dọn + đóng job mồ côi khi khởi động.
5. **Tốn tài nguyên DB:** chỉ tải cột cần, tránh truy vấn nặng, hủy job dừng sớm.
6. **Xóa nhầm khi nguồn trống/lỗi:** ngưỡng prune tối thiểu + sticky fields.
7. **Một site extra lỗi:** cô lập, không lan ra hệ thống.

---

## 15. Hạng mục còn ngỏ & Lộ trình (Open Items / Roadmap)

- **Module Lễ hội:** bổ sung filter/badge lễ hội trong các tab So sánh + Phủ sóng (đã có ở Trang chủ & báo cáo).
- **Hạ tầng:** phương án migrate sang VPS tại VN + tự host PostgreSQL (giảm độ trễ, hết cold start) — đã có kế hoạch, chưa thực thi.
- **Bảo mật:** cân nhắc refresh-token và rà soát toàn bộ secret qua biến môi trường.
- **Tự động hóa extra sites:** hiện một số site cần thao tác merge thủ công sang tab Main — có thể tự động hóa.

---

## Phụ lục A — Bản đồ Module ⇄ Năng lực

| Module (trang) | Năng lực phân tích sử dụng | Vai trò chính |
|----------------|----------------------------|---------------|
| Trang chủ CI | Insight/Alert, KPI tổng, trend, brief lễ hội | BGĐ + analyst |
| So sánh VTR | So sánh giá, tần suất, phủ sóng, profile đối thủ, ghép SP | Nhân viên nghiên cứu |
| Market Lab | Opportunity, phase, momentum, lịch cung, dự báo tuần | PT sản phẩm |
| Sản phẩm & Data | Tra cứu/làm sạch/chỉnh phân loại (workspace) | Nhân viên nghiên cứu |
| Sự kiện & Lễ hội | Coverage gap, pricing premium, forecast, marketing, heatmap | Marketing + nghiên cứu |
| Báo cáo BGĐ | Báo cáo CI (KPI + giá/tần suất/phủ sóng/lễ) + Báo cáo So sánh đối thủ 1:1 (lưu HTML, rebuild hằng ngày) | Admin → BGĐ |
| Vận hành | Thu thập, lập lịch, quản lý job, đồng bộ Sheet | Admin |
| Quy tắc phân loại | Phân loại & chuẩn hóa, áp rule, cấu hình phạm vi báo cáo So sánh đối thủ | Admin |
| Cài đặt | Quản lý người dùng & hồ sơ | Admin / mọi user |

*— Hết tài liệu —*
