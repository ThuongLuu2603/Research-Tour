/*  TEMPLATES.GS — đoạn code tái dùng cho scraper Google Apps Script.
    Copy hàm cần dùng, đổi tên/tham số cho khớp. Đọc SKILL.md trước.
    Lưu ý: gettuyenkh() / getduration() là HÀM CỦA USER (file khác) — chỉ GỌI, không định nghĩa lại.
*/

// ============================================================
//  HELPER CHUNG
// ============================================================

/** Chuẩn hóa text để so khớp header (thường, gộp khoảng trắng, giữ dấu tiếng Việt) */
function norm_(s) { return String(s == null ? "" : s).toLowerCase().replace(/\s+/g, " ").trim(); }

/** Tìm cột đầu tiên có header chứa 1 trong các từ khóa. Trả -1 nếu không có. */
function findCol_(header, keywords) {
  for (var c = 0; c < header.length; c++) {
    var h = norm_(header[c]);
    for (var k = 0; k < keywords.length; k++) if (h.indexOf(keywords[k]) !== -1) return c;
  }
  return -1;
}

/** Chuỗi/số -> số nguyên (bỏ ký tự không phải số). "7.490.000 đ" -> 7490000 */
function toNum_(v) {
  if (typeof v === "number") return Math.round(v);
  var d = String(v == null ? "" : v).replace(/[^\d]/g, "");
  return d ? parseInt(d, 10) : 0;
}

/** "dd/MM/yyyy" từ chuỗi HIỂN THỊ (D/M). Nhận cả ngày không năm "04/08" -> năm hiện tại. */
function toDateStr_(v) {
  var m = String(v == null ? "" : v).match(/(\d{1,2})\/(\d{1,2})(?:\/(\d{2,4}))?/);
  if (!m) return "";
  var y = m[3];
  if (!y) y = String(new Date().getFullYear());
  else if (y.length === 2) y = "20" + y;
  return ("0" + m[1]).slice(-2) + "/" + ("0" + m[2]).slice(-2) + "/" + y; // m[1]=ngày, m[2]=tháng
}

/** khóa sắp xếp dd/MM/yyyy -> yyyymmdd */
function keyDate_(d) { var p = d.split("/"); return p.length === 3 ? p[2] + p[1] + p[0] : d; }

/** ô có phải "thời gian" tour không? 5N4Đ / 7N6D / 1N / 2N1D / 10N9Đ (loại ghi chú/giá/ngày) */
function isDur_(s) { return /^\d{1,2}N\d{0,2}[ĐĐD]?$/i.test(String(s == null ? "" : s).replace(/\s/g, "")); }

/** lấy "thời gian" nhúng trong tên tour ("... HÀNG CHÂU 5N4Đ") nếu có */
function durFromName_(name) {
  var m = String(name == null ? "" : name).replace(/\s/g, "").match(/\d{1,2}N\d{1,2}[ĐĐD]/i);
  return m ? m[0] : "";
}

/** giải mã HTML entity thường gặp trong tên */
function decodeHtml_(s) {
  if (!s) return "";
  return s.replace(/&#(\d+);/g, function (_, n) { return String.fromCharCode(parseInt(n, 10)); })
          .replace(/&#x([0-9a-fA-F]+);/g, function (_, n) { return String.fromCharCode(parseInt(n, 16)); })
          .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&nbsp;/g, " ").trim();
}

/** strip tag -> text */
function stripTags_(s) { return String(s).replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim(); }

/** công thức link cho cột "Link tour" (locale VN dùng dấu ;) */
function hyperlink_(url, label) { return url ? '=HYPERLINK("' + url + '"; "' + (label || "Xem chi tiết") + '")' : ""; }


// ============================================================
//  A. WEBSITE — fetch + proxy + JSON-LD
// ============================================================

var BROWSER_HEADERS_ = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "vi,en;q=0.9"
};

/** fetch thường (kèm UA trình duyệt). Trả "" nếu không 200. */
function fetchHtml_(url) {
  var res = UrlFetchApp.fetch(url, { headers: BROWSER_HEADERS_, muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) { Logger.log("HTTP " + res.getResponseCode() + " : " + url); return ""; }
  return res.getContentText();
}

/** fetch qua ScraperAPI (lách Cloudflare). Cần PROXY_API_KEY. */
function fetchViaProxy_(targetUrl, PROXY_API_KEY) {
  if (!PROXY_API_KEY) throw new Error("Chưa điền PROXY_API_KEY (lấy ở scraperapi.com).");
  var api = "https://api.scraperapi.com/?api_key=" + PROXY_API_KEY +
            "&ultra_premium=true&url=" + encodeURIComponent(targetUrl);
  var res = UrlFetchApp.fetch(api, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) { Logger.log("Proxy " + res.getResponseCode() + " : " + targetUrl); return ""; }
  return res.getContentText();
}

/** Đọc JSON-LD ItemList (Product) từ HTML -> [{name,url,price,...}] */
function parseJsonLdItemList_(html) {
  var blocks = html.match(/<script[^>]*application\/ld\+json[^>]*>([\s\S]*?)<\/script>/gi);
  if (!blocks) return [];
  for (var b = 0; b < blocks.length; b++) {
    var raw = blocks[b].replace(/<script[^>]*>/i, "").replace(/<\/script>/i, "");
    var data; try { data = JSON.parse(raw); } catch (e) { continue; }
    var nodes = data["@graph"] || (Array.isArray(data) ? data : [data]);
    var list = null;
    for (var n = 0; n < nodes.length; n++)
      if (nodes[n] && nodes[n]["@type"] === "ItemList" && nodes[n].itemListElement) { list = nodes[n]; break; }
    if (!list) continue;
    return list.itemListElement.map(function (el) {
      var p = el.item || {}, of = p.offers || {};
      return {
        name: decodeHtml_(p.name || ""),
        url: (p.url || (p["@id"] || "").replace(/#.*$/, "")).trim(),
        price: (of.price || of.lowPrice) ? parseInt(of.price || of.lowPrice, 10) : "",
        keywords: p.keywords || ""
      };
    }).filter(function (t) { return t.url; });
  }
  return [];
}

/** Gọi nhiều URL song song theo lô (tránh timeout). cb(html, item) trả về dòng hoặc null. */
function fetchAllInBatches_(items, urlOf, cb, batchSize) {
  batchSize = batchSize || 25;
  var rows = [];
  for (var i = 0; i < items.length; i += batchSize) {
    var slice = items.slice(i, i + batchSize);
    var reqs = slice.map(function (t) { return { url: urlOf(t), headers: BROWSER_HEADERS_, muteHttpExceptions: true }; });
    var resps = [];
    try { resps = UrlFetchApp.fetchAll(reqs); } catch (e) { Logger.log("Lô " + i + " lỗi: " + e.message); }
    for (var k = 0; k < slice.length; k++) {
      var html = ""; try { html = resps[k].getContentText(); } catch (e) {}
      var row = cb(html, slice[k]); if (row) rows.push(row);
    }
    Logger.log("Đã xử lý " + Math.min(i + batchSize, items.length) + "/" + items.length);
  }
  return rows;
}

/** WooCommerce: bản đồ id -> giá (Store API, slim bằng _fields) */
function wooPriceMap_(SITE) {
  var map = {};
  for (var page = 1; page <= 50; page++) {
    var res = UrlFetchApp.fetch(SITE + "/wp-json/wc/store/v1/products?per_page=100&page=" + page + "&_fields=id,prices",
      { muteHttpExceptions: true });
    if (res.getResponseCode() !== 200) break;
    var arr = JSON.parse(res.getContentText()); if (!arr.length) break;
    arr.forEach(function (p) {
      var pr = p.prices || {};
      map[p.id] = (pr.price_range && pr.price_range.min_amount) ? parseInt(pr.price_range.min_amount, 10)
                : (pr.price ? parseInt(pr.price, 10) : "");
    });
    if (arr.length < 100) break;
  }
  return map;
}

/** WordPress taxonomy: bản đồ id -> tên */
function wpTermMap_(SITE, taxonomy) {
  var map = {};
  var res = UrlFetchApp.fetch(SITE + "/wp-json/wp/v2/" + taxonomy + "?per_page=100&_fields=id,name", { muteHttpExceptions: true });
  if (res.getResponseCode() === 200) JSON.parse(res.getContentText()).forEach(function (t) { map[t.id] = decodeHtml_(t.name); });
  return map;
}


// ============================================================
//  B. GOOGLE SHEET — đọc + dò cột + gộp block
// ============================================================
/*
  SƯỜN xử lý 1 tab sheet (gộp theo tour+giá, forward-fill, sticky thời gian).
  Đổi SOURCE_ID, gid, và cách map cột cho khớp.
*/
function readSheetTab_(SOURCE_ID, gid, airlineDefault) {
  var src = SpreadsheetApp.openById(SOURCE_ID);
  var byGid = {}; src.getSheets().forEach(function (s) { byGid[s.getSheetId()] = s; });
  var sheet = byGid[gid]; if (!sheet) { Logger.log("Không thấy gid=" + gid); return []; }

  var data = sheet.getDataRange().getDisplayValues();   // ⚠️ getDisplayValues (lỗi ngày)

  var hi = -1;
  for (var i = 0; i < Math.min(10, data.length); i++)
    if (data[i].some(function (c) { return norm_(c).indexOf("chương trình") !== -1; })) { hi = i; break; }
  if (hi === -1) return [];
  var H = data[hi];

  var cTour = findCol_(H, ["chương trình tiếng việt"]) >= 0 ? findCol_(H, ["chương trình tiếng việt"]) : findCol_(H, ["chương trình"]);
  var cDur = findCol_(H, ["độ dài"]); var cDurEff = cDur >= 0 ? cDur : 0; // thiếu header -> cột A
  var cDate = findCol_(H, ["lịch kh", "ngày kh", "ngày đi", "ngày khởi"]);
  var cSlot = findCol_(H, ["tổng số chỗ", "số lượng"]);
  var cAir = findCol_(H, ["hàng không", "hãng bay"]);
  var cHotel = findCol_(H, ["ks dự", "khách sạn"]);
  var cPrice = -1;
  for (var c = 0; c < H.length; c++) { var h = norm_(H[c]); if (h.indexOf("giá") !== -1 && h.indexOf("khuyến") === -1 && h.indexOf("com") === -1) { cPrice = c; break; } }
  if (cTour < 0 || cPrice < 0) return [];

  var rows = [], block = null, lastDur = "";
  function flush() {
    if (!block) return;
    Object.keys(block.groups).forEach(function (price) {
      var g = block.groups[price];
      var dates = g.dates.filter(function (v, i, a) { return a.indexOf(v) === i; })
        .sort(function (a, b) { return keyDate_(a) < keyDate_(b) ? -1 : 1; }).join(", ");
      rows.push({ tour: block.tour, dur: block.dur, hotel: block.hotel, air: block.air,
        price: parseInt(price, 10), dates: dates, slot: g.max });
    });
  }
  for (var r = hi + 1; r < data.length; r++) {
    var row = data[r];
    var tname = String(row[cTour] || "").replace(/\s+/g, " ").trim();
    var rowDur = ""; var raw = cDurEff < row.length ? String(row[cDurEff] || "").replace(/\s+/g, " ").trim() : "";
    if (isDur_(raw)) rowDur = raw.replace(/\s/g, ""); if (rowDur) lastDur = rowDur;
    if (tname && (!block || block.tour !== tname)) {     // chỉ mở block mới khi TÊN ĐỔI
      flush();
      block = { tour: tname, dur: rowDur || durFromName_(tname) || lastDur, hotel: "", air: airlineDefault || "", groups: {} };
    }
    if (!block) continue;
    if (rowDur) block.dur = rowDur;
    if (cHotel >= 0 && String(row[cHotel] || "").trim()) block.hotel = String(row[cHotel]).replace(/\s+/g, " ").trim();
    if (cAir >= 0 && String(row[cAir] || "").trim()) block.air = String(row[cAir]).replace(/\s+/g, " ").trim();
    var price = toNum_(row[cPrice]); if (!price) continue;
    var date = cDate >= 0 ? toDateStr_(row[cDate]) : "Hàng ngày"; if (!date) continue;
    var slot = cSlot >= 0 ? toNum_(row[cSlot]) : 0;
    var key = String(price);
    if (!block.groups[key]) block.groups[key] = { dates: [], max: 0 };
    block.groups[key].dates.push(date);
    if (slot > block.groups[key].max) block.groups[key].max = slot;
  }
  flush();
  return rows;
}


// ============================================================
//  GHI RA SHEET + HÀM CHẨN ĐOÁN
// ============================================================

/** Ghi 2D array ra sheet (xóa cũ, header, ép cột giá về số) */
function writeOut_(sheetName, headers, rows, priceColIndex1) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var out = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
  out.clear(); out.appendRow(headers);
  if (rows.length) out.getRange(2, 1, rows.length, rows[0].length).setValues(rows);
  if (priceColIndex1) out.getRange(2, priceColIndex1, Math.max(rows.length, 1), 1).setNumberFormat("#,##0");
  Logger.log("Hoàn thành: " + rows.length + " dòng.");
}

/** Mẫu hàm chẩn đoán Cloudflare — chạy riêng, xem ở Nhật ký */
function _diagnostic_(url, PROXY_API_KEY) {
  var html = PROXY_API_KEY ? fetchViaProxy_(url, PROXY_API_KEY) : fetchHtml_(url);
  Logger.log("len=" + html.length);
  Logger.log("Bị Cloudflare: " + (html.indexOf("Just a moment") !== -1 || html.indexOf("Attention Required") !== -1));
  Logger.log("Có ItemList: " + (html.indexOf("ItemList") !== -1));
  Logger.log(html.substring(0, 300));
}
