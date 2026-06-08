/**
 * Festival Proxy — Google Apps Script Web App
 *
 * MỤC ĐÍCH:
 *   Backend OTA platform (Render) không reach được vietnam.travel + visitvietnams.com
 *   do bị Cloudflare/WAF block IP range. Google Apps Script có Google IP được
 *   whitelist nên fetch được đầy đủ HTML.
 *
 * CÁCH DÙNG:
 *   1. Mở https://script.google.com → New project
 *   2. Copy toàn bộ code này paste vào file Code.gs
 *   3. Click "Deploy" → "New deployment"
 *   4. Type: "Web app"
 *   5. Execute as: "Me (your-email@gmail.com)"
 *   6. Who has access: "Anyone"  ← QUAN TRỌNG
 *   7. Click "Deploy" → Authorize → Copy URL "Web app URL"
 *      Format: https://script.google.com/macros/s/<SCRIPT_ID>/exec
 *   8. Gửi URL cho dev để config env var FESTIVAL_PROXY_URL trên Render
 *
 * TEST:
 *   Mở URL trên browser → trả về JSON array of events.
 *
 * QUOTA:
 *   - 6 phút execution time
 *   - 20MB response size (đủ cho ~500 events)
 *   - 50,000 URL fetches/ngày (rất nhiều)
 *
 * URL PATTERNS:
 *   ?source=all              → cả 2 nguồn (default)
 *   ?source=vietnam-travel   → chỉ vietnam.travel
 *   ?source=visitvietnams    → chỉ visitvietnams.com
 *   ?years=2026,2027         → custom years cho vietnam.travel (default current+next)
 *   ?max_vv_pages=10         → max pages cho visitvietnams (default 15)
 */

function doGet(e) {
  var params = (e && e.parameter) || {};
  var source = params.source || "all";
  var years;
  if (params.years) {
    years = params.years.split(",").map(function(y) { return parseInt(y.trim(), 10); }).filter(function(y) { return !isNaN(y); });
  } else {
    var now = new Date();
    years = [now.getFullYear(), now.getFullYear() + 1];
  }
  var maxVvPages = parseInt(params.max_vv_pages || "15", 10);

  var events = [];
  var errors = [];

  if (source === "all" || source === "visitvietnams") {
    try {
      var vv = scrapeVisitVietnams(maxVvPages);
      events = events.concat(vv);
    } catch (err) {
      errors.push({ source: "visitvietnams", error: String(err) });
    }
  }

  if (source === "all" || source === "vietnam-travel") {
    try {
      var vt = scrapeVietnamTravel(years);
      events = events.concat(vt);
    } catch (err) {
      errors.push({ source: "vietnam-travel", error: String(err) });
    }
  }

  var payload = {
    fetched_at: new Date().toISOString(),
    source: source,
    years: years,
    total: events.length,
    events: events,
    errors: errors,
  };
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

// ─── visitvietnams.com ──────────────────────────────────────────────────

function scrapeVisitVietnams(maxPages) {
  var page = 1;
  var out = [];
  var seen = {};

  while (page <= maxPages) {
    var url = "https://visitvietnams.com/en/events?page=" + page + "&keyword=";
    var response;
    try {
      response = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
    } catch (e) {
      break;
    }
    if (response.getResponseCode() !== 200) break;
    var html = response.getContentText();
    var cards = html.split('<div class="group flex flex-col h-full"');
    if (cards.length <= 1) break;

    var added = 0;
    for (var i = 1; i < cards.length; i++) {
      var cardHtml = cards[i];

      var titleMatch = cardHtml.match(/<h3[^>]*>[\s\S]*?<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/i);
      if (!titleMatch || titleMatch.length < 3) continue;
      var link = "https://visitvietnams.com" + titleMatch[1];
      var title = htmlDecode(stripTags(titleMatch[2]).trim());
      if (!title) continue;

      var slug = titleMatch[1].split("?")[0].split("/").filter(function(s){return s.length>0;}).pop() || "";
      if (!slug || seen[slug]) continue;
      seen[slug] = true;

      var dateMatch = cardHtml.match(/<div class="font-\[400\] text-\[14px\]"[^>]*>([\s\S]*?)<\/div>/i);
      var date = dateMatch ? htmlDecode(stripTags(dateMatch[1].replace(/<br\s*\/?>/gi, " ")).trim()) : "";

      var locMatch = cardHtml.match(/<p class="text-\[16px\] text-\[#494951\][^"]*"[^>]*>([\s\S]*?)<\/p>/i);
      var location = locMatch ? htmlDecode(stripTags(locMatch[1]).trim()) : "";

      var descMatch = cardHtml.match(/<div class="[^"]*truncate_3[^"]*"[^>]*>([\s\S]*?)<\/div>/i);
      var description = descMatch ? htmlDecode(stripTags(descMatch[1]).trim()) : "";

      var imgMatch = cardHtml.match(/<img[^>]+(?:src|data-src)="([^"]+)"/i);
      var imageUrl = imgMatch ? imgMatch[1] : "";
      if (imageUrl && imageUrl.indexOf("//") === 0) imageUrl = "https:" + imageUrl;

      out.push({
        source: "visitvietnams",
        slug: "vv-" + slug,
        name: title,
        date_text: date,
        location: location,
        description: description,
        image_url: imageUrl,
        source_url: link,
      });
      added++;
    }
    if (added === 0) break;
    Utilities.sleep(800);
    page++;
  }
  return out;
}

// ─── vietnam.travel ─────────────────────────────────────────────────────

function scrapeVietnamTravel(yearsArr) {
  var months = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var out = [];
  var seen = {};

  for (var y = 0; y < yearsArr.length; y++) {
    var year = yearsArr[y];
    for (var m = 0; m < months.length; m++) {
      var month = months[m];
      var url = "https://vietnam.travel/event?month=" + month + "&year=" + year;
      var response;
      try {
        response = UrlFetchApp.fetch(url, { muteHttpExceptions: true, followRedirects: true });
      } catch (e) {
        continue;
      }
      if (response.getResponseCode() !== 200) continue;
      var html = response.getContentText();
      if (html.indexOf('class="wrap-event"') === -1) {
        Utilities.sleep(500);
        continue;
      }
      var cards = html.split('<div class="wrap-event"');
      for (var i = 1; i < cards.length; i++) {
        var cardHtml = cards[i];

        var titleMatch = cardHtml.match(/<h5 class="title"[^>]*>([\s\S]*?)<\/h5>/i);
        var title = titleMatch ? htmlDecode(stripTags(titleMatch[1]).trim()) : "";
        if (!title) continue;

        var linkMatch = cardHtml.match(/<a[^>]*href="([^"]+)"[^>]*class="link"/i);
        var link = "";
        var slug = "";
        if (linkMatch) {
          var raw = linkMatch[1];
          link = raw.indexOf("http") === -1 ? "https://vietnam.travel" + raw : raw;
          link = htmlDecode(link);
          var path = link.split("?")[0];
          slug = path.split("/").filter(function(s){return s.length>0;}).pop() || "";
        }
        if (!slug) {
          slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").substr(0, 100);
        }
        if (seen[slug]) continue;
        seen[slug] = true;

        var dateMatch = cardHtml.match(/<span class="date"[^>]*>([\s\S]*?)<\/span>/i);
        var date = dateMatch ? htmlDecode(stripTags(dateMatch[1]).trim()) : "";

        var descMatch = cardHtml.match(/<p class="desc"[^>]*>([\s\S]*?)<\/p>/i);
        var description = descMatch ? htmlDecode(stripTags(descMatch[1]).trim()) : "";

        var imgMatch = cardHtml.match(/<img[^>]+(?:src|data-src)="([^"]+)"/i);
        var imageUrl = imgMatch ? imgMatch[1] : "";
        if (imageUrl && imageUrl.indexOf("//") === 0) imageUrl = "https:" + imageUrl;
        else if (imageUrl && imageUrl.charAt(0) === "/") imageUrl = "https://vietnam.travel" + imageUrl;

        out.push({
          source: "vietnam-travel",
          slug: slug,
          name: title,
          date_text: date,
          location: "",
          description: description,
          image_url: imageUrl,
          source_url: link,
        });
      }
      Utilities.sleep(800);
    }
  }
  return out;
}

// ─── helpers ────────────────────────────────────────────────────────────

function stripTags(s) {
  return (s || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

function htmlDecode(input) {
  if (!input) return "";
  input = String(input)
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, function(_, dec) { return String.fromCharCode(dec); });
  return input;
}
