"""Parse lich_kh (lịch khởi hành) into estimated monthly departure frequency."""
from __future__ import annotations

import calendar as _calendar
import re
from datetime import datetime, timedelta
from functools import lru_cache

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:\d{2}|\d{4}))\b")
# DD/MM thuần (không có năm) — "04/06", "11/06". Lookahead chặn nuốt nhầm DD/MM/YYYY.
DATE_NO_YEAR_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!/\d)")
# "Tháng 6: 13, 14, 20" hoặc "Tháng 6: 13/06, 14/06"
MONTH_DAYS_RE = re.compile(r"th[áa]ng\s*(\d{1,2})\s*[:\-]\s*([\d,\s/]+)", re.I)
# "Khởi hành ngày 17/06" → DD/MM (DATE_NO_YEAR_RE đã catch, nhưng giữ pattern để rõ ý)
KHOI_HANH_NGAY_RE = re.compile(r"kh[ởo]i\s*h[àa]nh\s*(?:ng[àa]y\s*)?(\d{1,2}/\d{1,2})", re.I)

EXTRA_DATES_RE = re.compile(r"\(\+(\d+)\s*ngày khác\)", re.I)
WEEKDAY_RE = re.compile(r"th[ứu]\s*(\d|cn|chủ nhật|chu nhat)", re.I)
# "Thứ 4 và thứ 7 hàng tuần", "Tối thứ 5 hàng tuần"
WEEKLY_RECURRING_RE = re.compile(
    r"(?:s[áa]ng|chi[ềe]u|t[ốo]i|tr[ưu]a)?\s*th[ứu]\s*(\d|cn|ch[ủu]\s*nh[ậa]t)"
    r"(?:[^.\d]*?(?:v[àa]|,|và|/)[^.\d]*?th[ứu]\s*(\d|cn|ch[ủu]\s*nh[ậa]t))?"
    r"[^.\d]*?h[àa]ng\s*tu[ầa]n",
    re.I,
)

PERIOD_WINDOW_DAYS = 45
# Expand recurring/no-year patterns trong bao nhiêu tháng tới (mặc định 12).
EXPAND_MONTHS_AHEAD = 12

# Python weekday(): Monday=0 … Sunday=6
WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]


def _today() -> datetime:
    return datetime.now()


def _resolve_year_for_day_month(day: int, month: int, today: datetime | None = None) -> int:
    """Năm gần nhất sao cho DD/MM chưa qua. Nếu đã qua trong năm hiện tại → năm tiếp theo."""
    today = today or _today()
    try:
        candidate = datetime(today.year, month, day)
    except ValueError:
        return today.year
    if candidate.date() >= today.date():
        return today.year
    return today.year + 1


def _resolve_common_year(dates_dm: list[tuple[int, int]], today: datetime | None = None) -> int:
    """Chọn 1 năm chung cho NHIỀU DD/MM trong cùng 1 chuỗi.

    Logic: nếu MỌI date đều đã qua trong năm hiện tại → năm tiếp theo. Ngược lại
    (có ít nhất 1 date trong tương lai) → năm hiện tại. Giữ past dates ở năm hiện
    tại thay vì split (vd: '04/06, 11/06, 18/06, 25/06' khi today=08/06 → tất cả
    đều 2026 thay vì 04/06/2027 + 11-25/06/2026)."""
    today = today or _today()
    if not dates_dm:
        return today.year
    has_future = False
    for d, mo in dates_dm:
        try:
            candidate = datetime(today.year, mo, d)
        except ValueError:
            continue
        if candidate.date() >= today.date():
            has_future = True
            break
    return today.year if has_future else today.year + 1


def _weekday_index_from_token(token: str) -> int | None:
    t = (token or "").strip().lower()
    if t in {"cn", "chủ nhật", "chu nhat"} or t.startswith("chủ"):
        return 6
    if t.isdigit():
        n = int(t)
        if 2 <= n <= 7:
            return n - 2
    return None


def parse_weekday_slots(lich_kh: str) -> dict[int, float]:
    """
    Phân bổ đoàn KH theo thứ trong tuần (0=Thứ 2 … 6=CN).
    Ưu tiên ngày cố định; sau đó lịch theo thứ; hàng ngày = đều 7 ngày.
    """
    from collections import defaultdict

    text = (lich_kh or "").strip()
    if not text:
        return {}

    lower = text.lower()
    if "hàng ngày" in lower or "hang ngay" in lower or "daily" in lower:
        return {i: 1.0 for i in range(7)}

    weights: dict[int, float] = defaultdict(float)
    dates = parse_departure_dates(text)
    if dates:
        for d in dates:
            weights[d.weekday()] += 1.0
        return dict(weights)

    for m in WEEKDAY_RE.finditer(text):
        idx = _weekday_index_from_token(m.group(1))
        if idx is not None:
            weights[idx] += 1.0

    if weights:
        return dict(weights)

    if "theo thứ" in lower:
        for i in range(5):
            weights[i] += 1.0
        return dict(weights)

    return {}


def vtr_period_months(vtr_dates: list[datetime]) -> set[tuple[int, int]]:
    return {(d.year, d.month) for d in vtr_dates}


def vtr_period_label(vtr_dates: list[datetime]) -> str:
    if not vtr_dates:
        return ""
    months = sorted(vtr_period_months(vtr_dates))
    if len(months) == 1:
        y, m = months[0]
        return f"T{m}/{y}"
    y0, m0 = months[0]
    y1, m1 = months[-1]
    return f"T{m0}/{y0}–T{m1}/{y1}"


@lru_cache(maxsize=16384)
def _parse_departure_dates_cached(lich_kh: str, token: int) -> tuple:
    """Memo theo (lich_kh, token DateFormatRule). lich_kh lặp rất nhiều trong dataset
    (hàng nghìn tour share cùng chuỗi lịch) → cache full kết quả parse → compare build
    nhanh hơn nhiều lần. token bump khi rule đổi → tự invalidate."""
    return tuple(_parse_departure_dates_impl(lich_kh))


def parse_departure_dates(lich_kh: str) -> list[datetime]:
    """Trích ngày khởi hành từ lich_kh — CACHED (memo theo lich_kh + token rule).

    parse_departure_frequency / _in_period gọi hàm này lặp nhiều lần/tour trong
    compare build → cache tránh re-parse regex + match rule mỗi lần.
    """
    if not lich_kh or not lich_kh.strip():
        return []
    try:
        import date_format_rules
        token = date_format_rules._cache_token
    except Exception:  # noqa: BLE001
        token = 0
    return list(_parse_departure_dates_cached(lich_kh, token))


def _parse_departure_dates_impl(lich_kh: str) -> list[datetime]:
    """Logic parse thật (gọi qua cache wrapper parse_departure_dates).

    Pattern được nhận:
      1. "17/06/2026", "17/06/26"                  — DD/MM/YYYY chuẩn
      2. "17/06", "Khởi hành ngày 17/06"           — DD/MM → suy năm gần nhất chưa qua
      3. "Tháng 6: 13, 14, 20, 21"                  — DD trong tháng X
      4. "04/06, 11/06, 18/06, 25/06"               — chuỗi DD/MM
      5. "Thứ 4 và thứ 7 hàng tuần"                 — expand 12 tháng
      6. "Tối thứ 5 hàng tuần"                      — expand 12 tháng
    """
    text = lich_kh or ""
    if not text.strip():
        return []

    # ── Thử DB-driven rule trước (admin định nghĩa qua UI) ──────────────────
    try:
        from date_format_rules import match_text as _match_dfr

        dfr_dates, dfr_type, _ = _match_dfr(text)
        if dfr_type is not None:
            # Match (kể cả skip/verbatim → trả [] để bỏ qua tour)
            return dfr_dates
    except Exception:
        # DB error / cache miss — fallback gracefully về logic hardcoded.
        pass

    dates: list[datetime] = []
    consumed_spans: list[tuple[int, int]] = []  # tránh double-count

    # 1. DD/MM/YYYY chuẩn — ưu tiên cao nhất, có năm explicit
    for m in DATE_RE.finditer(text):
        parts = m.group(1).split("/")
        if len(parts) != 3:
            continue
        d, mo, y = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        try:
            dates.append(datetime(y, mo, d))
            consumed_spans.append(m.span())
        except ValueError:
            continue

    today = _today()

    # 2. "Tháng X: D1, D2, D3" — gom mọi (day, month) trước, RỒI resolve năm chung.
    pending_dm: list[tuple[int, int]] = []
    for m in MONTH_DAYS_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed_spans):
            continue
        month = int(m.group(1))
        if not (1 <= month <= 12):
            continue
        days_text = m.group(2)
        for d_match in re.finditer(r"\b(\d{1,2})(?!\s*[/\-]\s*\d)", days_text):
            d = int(d_match.group(1))
            if 1 <= d <= 31:
                pending_dm.append((d, month))
        consumed_spans.append(m.span())

    # 3. DD/MM thuần (no year) — gom tiếp vào pending_dm
    for m in DATE_NO_YEAR_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed_spans):
            continue
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= d <= 31 and 1 <= mo <= 12:
            pending_dm.append((d, mo))

    # Resolve 1 năm CHUNG cho mọi DD/MM trong chuỗi (tránh split 2026/2027 khi
    # vài date đã qua, vài date còn tương lai).
    if pending_dm:
        common_year = _resolve_common_year(pending_dm, today)
        for d, mo in pending_dm:
            try:
                dates.append(datetime(common_year, mo, d))
            except ValueError:
                continue

    # 4. Weekly recurring — "Thứ X và thứ Y hàng tuần", "Tối thứ N hàng tuần"
    if not dates and WEEKLY_RECURRING_RE.search(text):
        weekdays_found = set()
        for m in WEEKLY_RECURRING_RE.finditer(text):
            for g in m.groups():
                if g is None:
                    continue
                idx = _weekday_index_from_token(g)
                if idx is not None:
                    weekdays_found.add(idx)
        # Bổ sung weekday từ WEEKDAY_RE nếu có (xử lý "thứ 2, thứ 4, thứ 6 hàng tuần")
        if "hàng tuần" in text.lower() or "hang tuan" in text.lower():
            for m in WEEKDAY_RE.finditer(text):
                idx = _weekday_index_from_token(m.group(1))
                if idx is not None:
                    weekdays_found.add(idx)
        if weekdays_found:
            cur = today.replace(hour=0, minute=0, second=0, microsecond=0)
            end = cur + timedelta(days=EXPAND_MONTHS_AHEAD * 31)
            d = cur
            while d <= end:
                if d.weekday() in weekdays_found:
                    dates.append(d)
                d += timedelta(days=1)

    # Sort + dedupe
    if dates:
        seen = set()
        uniq = []
        for d in sorted(dates):
            key = (d.year, d.month, d.day)
            if key not in seen:
                seen.add(key)
                uniq.append(d)
        return uniq
    return []


def has_recurring_schedule(lich_kh: str) -> bool:
    lower = (lich_kh or "").lower()
    return "hàng ngày" in lower or "hang ngay" in lower or "theo thứ" in lower or bool(WEEKDAY_RE.search(lower))


def schedules_overlap_vtr_period(vtr_dates: list[datetime], market_lich_kh: str) -> bool:
    """
    Tour thị trường có ngày KH cùng giai đoạn với VTR:
    cùng tháng/năm hoặc trong ±45 ngày; nếu VTR chỉ có lịch theo thứ/hàng ngày thì chấp nhận lịch tương tự.
    """
    if not vtr_dates:
        return has_recurring_schedule(market_lich_kh) or bool(parse_departure_dates(market_lich_kh))

    mkt_dates = parse_departure_dates(market_lich_kh)
    if not mkt_dates:
        return has_recurring_schedule(market_lich_kh)

    vtr_months = {(d.year, d.month) for d in vtr_dates}
    for md in mkt_dates:
        if (md.year, md.month) in vtr_months:
            return True
        for vd in vtr_dates:
            if abs((md - vd).days) <= PERIOD_WINDOW_DAYS:
                return True
    return False


def parse_departure_frequency_in_period(lich_kh: str, vtr_dates: list[datetime]) -> dict:
    """Tần suất trong giai đoạn so sánh (theo tháng KH của VTR)."""
    if not vtr_dates:
        return parse_departure_frequency(lich_kh)

    months = vtr_period_months(vtr_dates)
    explicit = parse_departure_dates(lich_kh)
    in_period = [d for d in explicit if (d.year, d.month) in months]

    if in_period:
        # BUG FIX: chia số ngày của TOUR NÀY cho số tháng RIÊNG mà tour có khởi hành,
        # KHÔNG chia cho TỔNG số tháng của cả vtr_dates (gồm mọi tour VTR trong segment).
        # Trước đây n_months = len(months) → tour chạy 2 tháng nhưng segment trải 7 tháng
        # → 8 ngày / 7 = 1.1 (deflate). Đúng phải 8 ngày / 2 tháng = 4 đoàn/tháng.
        own_months = {(d.year, d.month) for d in in_period}
        n_months = max(len(own_months), 1)
        monthly = max(1.0, round(len(in_period) / n_months, 1))
        return {
            "monthly_estimate": monthly,
            "explicit_dates": len(in_period),
            "pattern": "in_vtr_period",
            "label": f"~{monthly} đoàn/tháng ({len(in_period)} ngày trong giai đoạn VTR)",
        }

    if schedules_overlap_vtr_period(vtr_dates, lich_kh):
        return parse_departure_frequency(lich_kh)

    return {
        "monthly_estimate": 0.0,
        "explicit_dates": 0,
        "pattern": "outside_period",
        "label": "Ngoài giai đoạn VTR",
    }


def parse_departure_frequency(lich_kh: str) -> dict:
    """Đoàn/tháng = ĐẾM ngày khởi hành thực tế do "Quy tắc phân loại → Định dạng
    Ngày KH" (DateFormatRule) parse ra, chia cho số tháng các ngày đó trải.

    NGUỒN CHÂN LÝ = rule. KHÔNG còn heuristic hardcode ("hàng ngày"→30, "theo
    thứ"→×4, nhân ×1.5/×3/×4...). Rule recurring (weekly/monthly_recurring) tự
    expand 12 tháng → đếm ngày là ra rate. Không parse ra ngày nào (text không
    khớp rule) → 0 đoàn/tháng (BỎ QUA khỏi thống kê — "không khớp thì next").
    """
    text = (lich_kh or "").strip()
    if not text:
        return {"monthly_estimate": 0.0, "explicit_dates": 0, "pattern": "empty",
                "label": "Chưa rõ lịch KH"}

    dates = parse_departure_dates(text)  # đi qua DateFormatRule trước, rồi fallback pattern
    if not dates:
        return {"monthly_estimate": 0.0, "explicit_dates": 0, "pattern": "unmatched",
                "label": "Không khớp định dạng ngày KH"}

    own_months = {(d.year, d.month) for d in dates}
    n_months = max(len(own_months), 1)
    monthly = round(len(dates) / n_months, 1)
    return {
        "monthly_estimate": monthly,
        "explicit_dates": len(dates),
        "pattern": "from_dates",
        "label": f"~{monthly} đoàn/tháng ({len(dates)} ngày KH)",
    }
