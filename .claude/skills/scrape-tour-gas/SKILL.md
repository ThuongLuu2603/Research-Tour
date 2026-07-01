---
name: scrape-tour-gas
description: Viết hoặc SỬA code Google Apps Script để cào (scrape) dữ liệu tour từ website đối thủ HOẶC từ một Google Sheet khác, đổ về sheet theo dõi. Dùng khi user gửi 1 hàm GAS cào tour cần fix, nói "không lấy được data / web đổi cấu trúc / thiếu cột / sai ngày", hoặc yêu cầu cào thêm 1 website/sheet mới. Áp dụng cho các trang tour du lịch (WordPress, WooCommerce, Next.js SPA, theme Traveler/Shinetheme, nền tảng Vigo/Balotour) và các sheet giá tour nội bộ.
---

# Scrape Tour → Google Apps Script

Skill để xây/sửa code **Google Apps Script (GAS)** cào dữ liệu tour của đối thủ về Google Sheet theo dõi.

## Nguyên tắc số 1: CHẨN ĐOÁN TRƯỚC, VIẾT CODE SAU

**Không bao giờ tin selector/config cũ.** Web và sheet liên tục đổi cấu trúc. Luôn:
1. Tải dữ liệu THẬT về (PowerShell `Invoke-WebRequest`/`WebClient`, hoặc CSV export với sheet).
2. Soi cấu trúc thật (HTML/JSON/CSV) để xác định selector/cột đúng.
3. **Mô phỏng logic parse offline bằng Node** (`node` có sẵn) trên dữ liệu thật → xác nhận ra đúng dữ liệu.
4. Chỉ khi đó mới viết/sửa code GAS.
5. Sau khi viết, đối chiếu output mô phỏng với kỳ vọng, rồi giao file.

> Mã hóa: Google Sheets/web là UTF-8. PowerShell `Invoke-WebRequest.Content` hay đọc sai → dùng `New-Object System.Net.WebClient` với `$wc.Encoding=[System.Text.Encoding]::UTF8`.

## Output chuẩn (workbook theo dõi đối thủ)

Cột (tùy web mà thêm bớt 3 cột cuối):
```
Tên Công Ty | Thị trường | Tuyến tour | Tên Tour | Lịch trình |
Điểm khởi hành | Thời gian | Giá (từ) | Lịch khởi hành | Link tour [| Hãng bay | Khách sạn | Số chỗ]
```
Quy ước (giữ NHẤT QUÁN với các scraper cũ của user):
- **Tên Công Ty** = tên đối thủ cố định (vd "POSTUM", "Hải Đăng Travel").
- **Thị trường** = `gettuyenkh(tourName)` — **hàm của user, ở file khác, KHÔNG định nghĩa lại, chỉ gọi**.
- **Tuyến tour / Lịch trình** = thường để trống "".
- **Điểm khởi hành** = mặc định theo công ty (vd "Hồ Chí Minh" / "Hà Nội").
- **Link tour** = `'=HYPERLINK("' + url + '"; "Xem chi tiết")'` (dấu `;` cho locale VN).
- Cũng có thể gặp `getduration(...)` — hàm của user, giữ nguyên cách gọi.
- Ghi 1 lần bằng `setValues` (nhanh hơn `appendRow` nhiều); ép cột Giá về số: `range.setNumberFormat("#,##0")`.

Xem `templates.gs` để lấy hàm dựng dòng + các helper.

---

## PHẦN A — Cào từ WEBSITE

### Bước 1: Tải trang & nhận diện loại web
Tải HTML 1 trang list. Kiểm nhanh:
- Có còn class cũ không (`.product-small`, `.popular_box`...)? Nếu mất → web đổi markup.
- `_next/static` / `__NEXT_DATA__` → **Next.js SPA**. `__NUXT__` → Nuxt SPA. `id="app"` + ít HTML → SPA.
- `application/ld+json` → có **JSON-LD** (nguồn sạch).
- `wp-json` / `woocommerce` / `wp-content/themes/<theme>` → WordPress/WooCommerce.
- Header response `Server: cloudflare` + bị 403 → **Cloudflare chặn** (xem Pattern 6).

### Pattern 1 — HTML tĩnh + Cheerio / regex
HTML render sẵn, dùng `Cheerio.load(html)` + selector class. **Kiểm tra class còn tồn tại**; nếu theme đổi sang Tailwind (class utility), bỏ cách này.
- **⚠️ Cheerio của GAS (cheeriogs) PARSE HỎNG với HTML Tailwind**: class kiểu `[&amp;_a]:text-white`, `[&amp;&gt;a]:hover` (có `[ ] & > :`) làm parser lỗi → `$(".tour-item")` trả **0** dù HTML có. Triệu chứng: chạy ra 0 dòng, KHÔNG báo lỗi, GAS vẫn nhận đúng HTML (test bằng UA của GAS thấy class vẫn còn). → **Bỏ Cheerio, dùng REGEX**: `html.split('<div class="tour-item')` rồi regex từng card (regex miễn nhiễm class rối).
- **Fetch ĐÚNG trang chứa dữ liệu**: 1 trường có thể nằm ở trang khác (vd thời lượng "X Ngày Y Đêm" ở **trang chi tiết tour**, KHÔNG ở trang đặt chỗ/booking — trang booking "Thời gian" chỉ là giờ bay). Kiểm tra trang thật trước.
- **HTML mã hóa entity số**: nguồn hay viết "Ng&#224;y", "Đ&#234;m" (à=#224, ê=#234). Regex tìm "Ngày" sẽ **thất bại**. → Giải mã trước: `html.replace(/&#(\d+);/g, function(_,n){return String.fromCharCode(+n);})` rồi mới regex; hoặc dùng `Cheerio.load(html)` + `.text()` (tự decode).
- Lấy thời lượng theo thứ tự: neo nhãn `Thời gian:[\s\S]{0,80}?(\d+)\s*Ngày\s*(\d+)\s*Đêm` → cụm `(\d+)\s*Ngày\s*(\d+)\s*Đêm` đầu tiên → nhúng trong tên/mã tour. **Đừng** đổ tên tour vào hàm format thời lượng (dễ trả về cả tên).

### Pattern 2 — Theme Traveler/Shinetheme (AJAX có nonce)
Lịch khởi hành/giá nạp động qua `admin-ajax.php`. Cách lấy:
1. Trong trang chi tiết tìm `data-action="st_get_availability_tour_frontend"`, `data-tour-id`, `data-posttype`.
2. Tìm trong JS theme (vd `single-tour-detail.js`) hàm gọi: params `action, start, end, tour_id, security`.
3. `security` = `st_params._s` — lấy giá trị `"_s":"<nonce>"` trong HTML trang. (nonce sống ~12–24h, fetch trang nào lấy nonce trang đó.)
4. POST `wp-admin/admin-ajax.php` → JSON `{events:[{date, status, adult_price,...}]}`. **Chỉ lấy `status === "available"`**; loại `not_available` (đệm lịch). Query 1 lần `start=hôm nay`, `end=+N tháng` (vùng quá xa thường mở "mọi ngày" = nhiễu).

### Pattern 3 — WooCommerce (REST/Store API) ⭐ ưu tiên
Không cào HTML, gọi JSON API có sẵn (không cần key):
- Danh sách + giá: `/wp-json/wc/store/v1/products?per_page=100&page=N&_fields=id,prices`
  → `prices.price` (đã gồm KM) hoặc `prices.price_range.min_amount` (tour variable).
- Trường tùy chỉnh (thời lượng, điểm đi, ngày...): `/wp-json/wp/v2/product?per_page=100&_fields=id,title.rendered,link,<taxonomy...>` — các taxonomy trả về **ID**, phải map sang tên qua `/wp-json/wp/v2/<taxonomy>?per_page=100&_fields=id,name`.
- Ghép 2 nguồn theo **`id`** (cùng post id).
- **`_fields` cực quan trọng**: giảm payload (Store API 6.9MB → 30KB). Phân trang tới khi `< per_page`.
- `X-WP-Total` header = tổng số.

### Pattern 4 — Next.js / Nuxt SPA → tìm API backend
HTML rỗng, data nạp qua API. Cách lần ra API:
1. Quét các file `/_next/static/chunks/*.js`, tìm `baseURL`, `NEXT_PUBLIC_*`, domain `admin.<site>` / `api.<site>`.
2. Tìm endpoint trong chunk của trang (vd `app/search/page-*.js`): chuỗi như `Balotour/Tour/tourList?off=...&keyword=...`, header `x-api-key`.
3. Lấy giá trị hằng (vd `d0k`="API base", `zvo`="api_key", token...) trong chunk định nghĩa.
4. Gọi thẳng API JSON. Lưu ý nền tảng **Vigo/Balotour**: `https://admin.<site>/api/Balotour/Tour/tourList?off=<SỐ LƯỢNG>` (param `off` = số bản ghi, KHÔNG phải offset!), chi tiết `Balotour/Tour/tour_info?permalink=<slug>` → `tour_open_list[]` chứa `date_start_tour` + `price_1_person`.

### Pattern 4b — Bảng DataTables server-side (ASP.NET / jQuery)
HTML có `<table>` rỗng (`<td>`=0), data nạp qua AJAX. Tìm `sAjaxSource: '/.../Lists'`, `bServerSide:true`, `fnServerParams` (các filter custom). Gọi thẳng:
`POST <sAjaxSource>` body = params DataTables (`sEcho, iDisplayStart, iDisplayLength, iColumns, iSortingCols`) + filter custom (vd `Ngay`, `NoiXuatPhatId`, `IsNgay`). Trả `{iTotalDisplayRecords, aaData:[{...}]}`. **Phân trang** bằng `iDisplayStart`/`iDisplayLength` (đặt quá lớn vd 2000 có thể bị server từ chối → dùng 100/trang). Mỗi `aaData[i]` thường là **HTML từng ô** → regex bóc field (vd `<span>giá</span>`, `Mã Lịch:<b>...</b>`, `Đi:<b>ngày</b>`). Lọc bỏ `data-*`/`style` khi lấy số (đừng strip cả ô). Vd Triều Hảo: `/DieuHanhTour/DatCho/Lists` cho cả tên/thời lượng/giá/ngày/hãng/số chỗ trong 1 endpoint.

### Pattern 5 — JSON-LD (schema.org)
Trang có `<script type="application/ld+json">` chứa `@graph` → node `@type=ItemList` → `itemListElement[].item` (Product): `name, url, offers.price | offers.lowPrice, keywords` (đôi khi chứa phương tiện), `productID`. Parse rất sạch cho tên/link/giá. Thời gian thường nằm trong tên ("6N5Đ"); ngày/sao có thể phải lấy từ thẻ card hoặc trang chi tiết.

### Pattern 6 — Bị Cloudflare chặn (GAS không vào được)
Triệu chứng: chạy ra **0 dòng**, hàm chẩn đoán thấy **HTTP 403** + HTML chứa "Just a moment"/"Attention Required".
- **Nguyên nhân**: Cloudflare chặn theo **dải IP máy chủ Google** (nơi GAS chạy). Giả `User-Agent` trình duyệt **KHÔNG cứu được** nếu là chặn IP. Proxy/render công cộng (allorigins, corsproxy, r.jina.ai) cũng hay bị chặn.
- **Cách lách**: gọi qua **scraping API có residential proxy** (ScraperAPI `&ultra_premium=true`, ZenRows, ScrapingBee). User tự đăng ký free key, dán vào hằng `PROXY_API_KEY`. **Tiết kiệm credit**: chỉ gọi các trang DANH SÁCH (vài lượt), tránh vào từng trang chi tiết.
- Luôn kèm **hàm chẩn đoán** `_diagnostic()` để user tự xác nhận đã qua Cloudflare chưa (log HTTP code, có "ItemList", số dòng parse được).

> Nếu chỉ test được từ IP nhà (không bị chặn) mà GAS thì bị: nhớ test lại bằng đúng User-Agent của GAS `"Mozilla/5.0 (compatible; Google-Apps-Script; beanserver; ...)"`. Nếu vẫn 403 từ máy mình → khả năng cao là IP-block, UA vô dụng.

---

## PHẦN B — Cào từ GOOGLE SHEET khác

### Đọc dữ liệu
```javascript
var src = SpreadsheetApp.openById(SOURCE_ID);          // user phải có quyền XEM nguồn
var byGid = {}; src.getSheets().forEach(s => byGid[s.getSheetId()] = s);
var data = byGid[gid].getDataRange().getDisplayValues(); // ⚠️ getDisplayValues, KHÔNG getValues
```

### ⚠️ BẪY CHẾT NGƯỜI: NGÀY THÁNG — luôn dùng `getDisplayValues()`
- `getValues()` trả **Date object**. Ô gõ "04/08" (ý: 4/8 D/M) nhưng Google locale Mỹ lưu ngầm = **8 tháng 4** → format ra "08/04" → **SAI THÁNG KHỞI HÀNH**.
- `getDisplayValues()` trả đúng **chuỗi đang hiển thị** "04/08" → đọc **D/M** (ngày trước) → 4 tháng 8. Đúng.
- Cách kiểm tra format nguồn: gviz API `/.../gviz/tq?tqx=out:json&gid=<gid>` → ô ngày có `"v":"Date(y,m,d)"` (giá trị ngầm) và `"f":"04/08"` (hiển thị). Quét toàn bộ: nếu có ngày nào **phần 2 > 12** → nguồn là M/D (hiếm). Nếu nhiều ngày **phần 1 > 12** → khẳng định D/M.

### ⚠️ BẪY LỚN: NHIỀU scraper CÙNG 1 PROJECT → XUNG ĐỘT TÊN HÀM (im lặng)
Apps Script gộp MỌI file .gs trong 1 project vào CHUNG 1 namespace. Nhiều scraper định nghĩa hàm TRÙNG TÊN (`parseDays_`, `toNum_`, `cleanText_`...) hành vi khác nhau → **bản load SAU ĐÈ bản trước**, KHÔNG báo lỗi. Scraper gọi `parseDays_(tháng, ngày, năm)` có thể chạy nhằm bản `(cell, năm)` của file khác → trả rỗng → **0 dòng** dù code + dữ liệu ĐÚNG.
- **Triệu chứng:** code đúng, diag in ra header/cột chuẩn, nhưng **0 dòng**, KHÔNG lỗi. (DOLPHIN bị đúng cái này.)
- **FIX:** đặt tên helper RIÊNG cho TỪNG scraper — prefix `vq`/`dl`/`vf`... (vd `dlDays`, `vfNum`, `vfFindCol`). Hoặc mỗi scraper 1 project riêng (standalone phải đổi `getActiveSpreadsheet()` → `openById(ID)` + copy `gettuyenkh` vào mỗi project).

### ⚠️ Mô phỏng offline: dùng CSV, ĐỪNG dùng gviz để bắt chước getDisplayValues
`getDisplayValues()` ≈ **CSV export** (cả 2 giữ lưới ĐẦY ĐỦ, ô gộp có giá trị ở dòng gốc). **gviz JSON NÉN ô gộp** (bỏ dòng trống) → lệch dòng/cột → sim bằng gviz ra SAI (vd `date=-1`). → Mô phỏng parse bằng **CSV** mới khớp GAS. (gviz CHỈ để check format ngày D/M qua field `v`/`f`.) Khi GAS ra 0 dòng mà CSV sim ra data → **nghi xung đột tên hàm TRƯỚC**, rồi mới tới quyền/gid.

### Dò cột theo TÊN HEADER (không gán cứng vị trí)
Mỗi tab thường 1 layout. Tìm dòng header (chứa "CHƯƠNG TRÌNH"), rồi map cột theo từ khóa (chuẩn hóa lowercase, gộp khoảng trắng, giữ dấu tiếng Việt):
| Trường | Từ khóa header |
|---|---|
| Tên tour | "chương trình" (ưu tiên "...tiếng việt") |
| Thời gian | "độ dài" (thiếu header → thử **cột A**) |
| Ngày khởi hành | "lịch kh" / "ngày kh" / "ngày đi" / "ngày khởi" |
| Giá | chứa "giá" và KHÔNG chứa "khuyến"/"com" |
| Hãng bay | "hàng không" / "hãng bay" (thiếu → điền cứng theo tab) |
| Khách sạn | "ks dự" / "khách sạn" |
| Số chỗ | "tổng số chỗ" / "số lượng" / "còn nhận" |

> **⚠️ BẪY UNICODE NFC/NFD khi dò header:** CSV export (và đôi khi cell) của Google trả ký tự tiếng Việt dạng **tổ hợp (NFD)** — vd "à" = a + dấu huyền rời — khác chuỗi keyword gõ trong code (NFC). `indexOf("hàng không")` sẽ **trượt → cột = -1 → mất dữ liệu IM LẶNG** (vd cột Hãng bay rỗng cả loạt tab dù header có "HÀNG KHÔNG"). FIX: chuẩn hóa **`.normalize("NFC")`** cho CẢ header lẫn keyword trong hàm `norm_`/`findCol_`. (Apps Script V8 có `String.normalize`.)

### Date tách 2 cột THÁNG + NGÀY (vd VIETQUEEN)
Một số nguồn để **THÁNG** ("Tháng 7") và **NGÀY KHỞI HÀNH** ("18, 25" — list ngày trong tháng) ở 2 cột riêng. Ghép: THÁNG **sticky** (forward-fill) + tách từng số trong ô ngày (`split(/[,;]/)`, bỏ chú thích `(...)`), token dạng "1/9" = ngày/tháng rõ (override tháng). **GIÁ cũng hay merge** (ô trống = kế thừa giá trên) → forward-fill giá trong block. Mở block mới khi **ô THỜI GIAN có thời lượng hợp lệ** (mỗi chương trình có dur ở dòng đầu) — cách này TÁCH đúng 2 chương trình **trùng tên khác giá/thời lượng** (đừng chỉ dựa "tên đổi").

### Ô gộp (merge) & forward-fill / sticky
- Mỗi tour nhiều dòng (mỗi ngày 1 dòng), ô tên/thời gian/khách sạn chỉ điền dòng đầu (merge) → các dòng sau rỗng. **Forward-fill** trong block.
- **Chỉ mở block mới khi TÊN TOUR ĐỔI** (tên lặp lại = vẫn cùng tour, đừng reset → tránh mất thời gian & tách nhầm nhóm giá). *Ngoại lệ:* nguồn có nhiều chương trình **trùng tên** (PHÚ QUỐC ×2 khác giá) → mở block theo **ô thời lượng** thay vì tên.
- Ô "Độ dài" có thể merge cho cả tour chiều đi + chiều về (tên khác nhau) → dùng **sticky**: giữ giá trị "thời gian" hợp lệ gần nhất, dòng/block sau rỗng thì kế thừa.
- **Lọc đúng dạng** thời gian (`/^\d{1,2}N\d{0,2}[ĐD]?$/i`) để bỏ ghi chú lọt cột (vd "*** Lưu ý...").

### Gộp & ngày
- Gộp theo **(tour + giá)**: cùng tour cùng giá → gộp ngày 1 dòng; khác giá → tách dòng. (Hỏi user nếu chưa rõ: 1 dòng/tour hay 1 dòng/ngày; Số chỗ = tổng hay còn nhận.)
- Chuẩn hóa ngày → `dd/MM/yyyy`; ngày không năm → năm hiện tại (cân nhắc +1 năm nếu đã qua); dedupe + sort.
- Giá → số. **⚠️ ĐỪNG dùng `String(v).replace(/[^\d]/g,'')`** nếu ô có thể chứa **2 giá** (vd "7.590.000 (Đón tại Hà Nội)\n7.190.000 (Đón tại cửa khẩu)") — gom hết chữ số sẽ dính thành "75.900.007.190". → Lấy **cụm số ĐẦU TIÊN**: `var m=String(v).match(/\d[\d.,]*\d|\d/); d=m?m[0].replace(/[^\d]/g,''):''`. (Giá đầu thường là giá điểm khởi hành chính.)

---

## Kỹ thuật GAS quan trọng
- **`UrlFetchApp.fetchAll(requests)`**: gọi song song theo lô (vd 25–40/lô) cho nhiều trang chi tiết → tránh timeout 6 phút. Mỗi request `{url, headers, muteHttpExceptions:true}`.
- **⚠️ Site sau Cloudflare: fetch SONG SONG bị trả THIẾU/rỗng.** dulichviet.com.vn fetchAll 3 URL cùng lúc → chỉ ~389 tour; fetch TUẦN TỰ + `Utilities.sleep(1500)` giữa lần → đủ ~650. Với site Cloudflare, ít URL thì fetch tuần tự có nghỉ (đủ + ít bị throttle); nếu ra 0 dòng/"just a moment" → IP datacenter GAS bị chặn, fallback ScraperAPI (`?api_key=..&url=`, 1 credit/URL) hoặc chạy Node LOCAL. Landing dulichviet chứa SẴN toàn bộ tour (khỏi phân trang; `?page=N` chỉ trả 9 tour cố định = giả). Giá theo ngày ở detail (`data-day`+`data-price`) nhưng detail ~1.16MB × ~650 tour ≈ 750MB → KHÔNG fetch hết trong GAS, chỉ lấy giá "từ" của listing.
- **⚠️ Endpoint `load-more`/phân trang + server CHẬP CHỜN → timeout 6' dù dùng fetchAll.** Dội quá nhiều request 1 lúc (vd 9 cat × 11 trang = 99) làm server NGHẸN → nhiều request treo 20–60s → fetchAll không kịp 6'. Lại còn phần lớn trang RỖNG (phí). **FIX: fetch THÍCH ỨNG THEO VÒNG** — mỗi vòng chỉ bắn 1 trang cho mỗi chuyên mục còn "sống", trang RỖNG (0 card) thì LOẠI chuyên mục khỏi vòng sau, `Utilities.sleep(200)` giữa vòng. World Sun Travel: 99 req/>6' → **38 req/~25s**. Đừng hardcode số trang (site thêm/bớt tour); dừng khi rỗng + trần `MAX_PAGE`.
- **Hạn mức** tài khoản thường ~100MB dữ liệu nhận/ngày → dùng `_fields`, gọi ít trang, batch. Cảnh báo user nếu 1 lần chạy tải nhiều (vd 94 trang chi tiết).
- `setValues` ghi 1 lần; `setNumberFormat("#,##0")` cho cột giá để Sheets không hiểu nhầm số thành ngày.
- Giải mã HTML entity trong tên (`&#8211;`, `&amp;`...).
- Luôn `muteHttpExceptions:true` + kiểm `getResponseCode()`.

## Checklist BẪY (tự rà trước khi giao)
- [ ] Sheet nguồn: dùng **`getDisplayValues`** chưa? (lỗi ngày D/M ↔ M/D)
- [ ] Web SPA? → tìm API JSON, đừng cào HTML rỗng.
- [ ] Class/markup còn đúng không? (theme có thể đổi sang Tailwind, mất class ngữ nghĩa)
- [ ] Cloudflare 403? → cần proxy API + hàm chẩn đoán.
- [ ] Ngày không có năm? → thêm năm.
- [ ] Ô merge → forward-fill / sticky; tên lặp lại không tách block.
- [ ] Param phân trang đúng nghĩa? (vd Vigo `off` = số lượng, không phải offset)
- [ ] Lọc rác (ghi chú lọt cột; ngày rác như 18/11/1989 → lọc theo năm hợp lý).
- [ ] Giữ nguyên `gettuyenkh()`/`getduration()` của user, không định nghĩa lại.
- [ ] Đã mô phỏng bằng Node trên dữ liệu thật chưa?

## Mẫu code
Toàn bộ helper tái dùng (đọc sheet, dò cột, parse ngày/giá, JSON-LD, fetchAll, proxy, dựng dòng) ở **`templates.gs`** cùng thư mục skill này.
