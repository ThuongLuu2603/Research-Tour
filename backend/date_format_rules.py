"""Pattern-based date format rule — DSL compiler + matcher.

DSL syntax (case-insensitive):
  {dd}        → match 1-2 digit day (1-31)
  {mm}        → match 1-2 digit month (1-12)
  {yyyy}      → match 4-digit year
  {yy}        → match 2-digit year (cộng 2000)
  {weekday}   → match "2|3|4|5|6|7|cn|chủ nhật|chu nhat"
  {...}       → wildcard (".*?")
  literal text → re.escape()
  Whitespace → "\\s*" (flex)

Output types:
  dates                → extract DD/MM/YYYY → list[datetime] (suy năm nếu thiếu)
  weekly               → extract {weekday} → expand 12 tháng
  monthly_recurring    → extract {dd} → expand 12 tháng
  skip / verbatim      → trả [] (bỏ qua tour khỏi stats)

API:
  compile_pattern(pattern) -> re.Pattern
  apply_rule(rule, text, today) -> list[datetime] | None
  match_text(text, today) -> tuple[list[datetime], str | None]  # (dates, output_type)
  invalidate_date_format_cache()
"""
from __future__ import annotations

import logging
import re
import threading
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

EXPAND_MONTHS_AHEAD = 12

# Cache invalidation token — lru_cache không tự reset; thay vào đó bump token mỗi lần
# rule mutation → key sẽ khác → cache mới.
_cache_token = 0
_token_lock = threading.Lock()


def invalidate_date_format_cache() -> None:
    """Bump cache token + clear lru_cache compiled patterns."""
    global _cache_token
    with _token_lock:
        _cache_token += 1
    _compile_pattern_cached.cache_clear()
    _get_active_rules_cached.cache_clear()


# ── DSL compile ──────────────────────────────────────────────────────────────

# Token regex: tìm {dd}, {mm}, {yyyy}, {yy}, {weekday}, {...} HOẶC literal char
_TOKEN_RE = re.compile(
    r"\{(dd|mm|yyyy|yy|weekday|\.\.\.)\}",
    re.IGNORECASE,
)

# Trong DSL, placeholder map sang nhóm regex tương ứng. Group name kèm số thứ tự
# để hỗ trợ pattern có nhiều {dd} liên tiếp (vd "Tháng {mm}: {dd}, {dd}, {dd}").
_PLACEHOLDER_TO_REGEX: dict[str, str] = {
    "dd": r"(\d{1,2})",
    "mm": r"(\d{1,2})",
    "yyyy": r"(\d{4})",
    "yy": r"(\d{2})",
    "weekday": r"(\d|cn|ch[ủu]\s*nh[ậa]t)",
    "...": r".*?",
}


def _compile_pattern_impl(pattern: str) -> tuple[re.Pattern, list[str]]:
    """Compile DSL pattern → (regex, placeholder_order).

    placeholder_order: danh sách tên placeholder theo thứ tự xuất hiện
    (vd ['mm', 'dd', 'dd', 'dd']). Dùng để map captured groups → ý nghĩa.
    """
    parts: list[str] = []
    placeholder_order: list[str] = []
    i = 0
    pat = pattern.strip()
    while i < len(pat):
        m = _TOKEN_RE.match(pat, i)
        if m:
            name = m.group(1).lower()
            parts.append(_PLACEHOLDER_TO_REGEX[name])
            if name != "...":
                placeholder_order.append(name)
            i = m.end()
        else:
            ch = pat[i]
            if ch.isspace():
                # Một hoặc nhiều whitespace trong DSL → \s* trong regex (flex match).
                # Skip mọi whitespace tiếp theo để không append nhiều \s*.
                parts.append(r"\s*")
                while i < len(pat) and pat[i].isspace():
                    i += 1
                continue
            else:
                parts.append(re.escape(ch))
                i += 1

    # Wrap full match: anchor 2 đầu để tránh partial match nuốt phần text khác.
    # Cho phép whitespace 2 bên — text gốc có thể có space thừa.
    regex_str = r"^\s*" + "".join(parts) + r"\s*$"
    try:
        return re.compile(regex_str, re.IGNORECASE), placeholder_order
    except re.error as e:
        raise ValueError(f"Pattern không hợp lệ ({pattern}): {e}") from e


@lru_cache(maxsize=512)
def _compile_pattern_cached(pattern: str, token: int) -> tuple[re.Pattern, list[str]]:
    return _compile_pattern_impl(pattern)


def compile_pattern(pattern: str) -> re.Pattern:
    """Public API — compile DSL → re.Pattern. Token là dummy để integrate cache."""
    regex, _ = _compile_pattern_cached(pattern, _cache_token)
    return regex


def _compile_with_order(pattern: str) -> tuple[re.Pattern, list[str]]:
    return _compile_pattern_cached(pattern, _cache_token)


# ── Resolve helpers ──────────────────────────────────────────────────────────


def _today() -> datetime:
    return datetime.now()


def _resolve_year_for_dm(day: int, month: int, today: datetime) -> int:
    try:
        candidate = datetime(today.year, month, day)
    except ValueError:
        return today.year
    if candidate.date() >= today.date():
        return today.year
    return today.year + 1


def _resolve_common_year(dates_dm: list[tuple[int, int]], today: datetime) -> int:
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
    """2|3|4|5|6|7 → 0..5 (Monday..Saturday); CN/Chủ nhật → 6."""
    t = (token or "").strip().lower()
    if not t:
        return None
    if t in {"cn"} or t.startswith("chủ") or t.startswith("chu"):
        return 6
    if t.isdigit():
        n = int(t)
        if 2 <= n <= 7:
            return n - 2
    return None


# ── Apply rule ───────────────────────────────────────────────────────────────


def apply_rule(rule: Any, text: str, today: datetime | None = None) -> list[datetime] | None:
    """Try match rule trên text → trả list[datetime] hoặc None nếu không match.

    Trả [] (list rỗng) nếu output_type=skip/verbatim → caller hiểu là "match
    nhưng bỏ qua tour". None = không match → caller thử rule khác.
    """
    if not text or not text.strip():
        return None
    today = today or _today()

    try:
        regex, order = _compile_with_order(rule.pattern)
    except ValueError as e:
        logger.warning("compile pattern failed (rule_id=%s): %s", getattr(rule, "id", None), e)
        return None

    m = regex.match(text)
    if not m:
        return None

    output_type = (rule.output_type or "").strip().lower()

    if output_type in {"skip", "verbatim"}:
        return []

    groups = list(m.groups())
    # Map (placeholder name, captured value) theo thứ tự
    captured: list[tuple[str, str]] = list(zip(order, groups))

    if output_type == "weekly":
        weekdays: set[int] = set()
        for name, val in captured:
            if name == "weekday":
                idx = _weekday_index_from_token(val)
                if idx is not None:
                    weekdays.add(idx)
        if not weekdays:
            return []
        out: list[datetime] = []
        cur = today.replace(hour=0, minute=0, second=0, microsecond=0)
        end = cur + timedelta(days=EXPAND_MONTHS_AHEAD * 31)
        d = cur
        while d <= end:
            if d.weekday() in weekdays:
                out.append(d)
            d += timedelta(days=1)
        return out

    if output_type == "monthly_recurring":
        # Lấy {dd} đầu tiên — expand mỗi tháng trong 12 tháng tới
        day_val: int | None = None
        for name, val in captured:
            if name == "dd":
                try:
                    day_val = int(val)
                    break
                except ValueError:
                    pass
        if day_val is None or not (1 <= day_val <= 31):
            return []
        out = []
        for offset in range(EXPAND_MONTHS_AHEAD):
            y = today.year + ((today.month - 1 + offset) // 12)
            mo = ((today.month - 1 + offset) % 12) + 1
            try:
                cand = datetime(y, mo, day_val)
                if cand.date() >= today.date():
                    out.append(cand)
            except ValueError:
                continue
        return out

    if output_type == "dates":
        return _extract_dates_from_captured(captured, today)

    logger.warning("unknown output_type=%r (rule_id=%s)", output_type, getattr(rule, "id", None))
    return None


def _extract_dates_from_captured(
    captured: list[tuple[str, str]],
    today: datetime,
) -> list[datetime]:
    """Convert captured (name, val) → list[datetime].

    Strategy 2-pass:
      Pass 1: thu thập indices các dd/mm/yyyy/yy theo thứ tự, giá trị parse.
      Pass 2: cho mỗi dd, tìm mm/yyyy gần nhất (trước HOẶC sau) — vd "{dd}/{mm}/{yyyy}"
              thì mm/yyyy nằm SAU dd; còn "Tháng {mm}: {dd}, {dd}" thì mm nằm TRƯỚC.

    Logic: nếu có >=1 mm trước dd → dùng mm gần nhất TRƯỚC; nếu không (mm chỉ sau)
    → dùng mm đầu tiên SAU. Tương tự yyyy/yy.
    """
    # Pass 1: build (idx, kind, value) list
    items: list[tuple[int, str, int]] = []
    for idx, (name, val) in enumerate(captured):
        if not val or name == "weekday":
            continue
        try:
            n = int(val)
        except ValueError:
            continue
        if name == "mm" and 1 <= n <= 12:
            items.append((idx, "mm", n))
        elif name == "yyyy":
            items.append((idx, "yyyy", n))
        elif name == "yy":
            items.append((idx, "yyyy", 2000 + n))
        elif name == "dd" and 1 <= n <= 31:
            items.append((idx, "dd", n))

    dd_items = [(i, v) for (i, k, v) in items if k == "dd"]
    mm_items = [(i, v) for (i, k, v) in items if k == "mm"]
    yr_items = [(i, v) for (i, k, v) in items if k == "yyyy"]

    def _nearest(target_idx: int, candidates: list[tuple[int, int]]) -> int | None:
        """Tìm value gần nhất: ưu tiên trước (last <= target), fallback sau (first > target)."""
        if not candidates:
            return None
        prev_val: int | None = None
        for ci, cv in candidates:
            if ci <= target_idx:
                prev_val = cv
            else:
                if prev_val is not None:
                    return prev_val
                return cv
        return prev_val

    entries: list[dict[str, int]] = []
    for dd_idx, dd_val in dd_items:
        mo = _nearest(dd_idx, mm_items)
        yr = _nearest(dd_idx, yr_items)
        entries.append({
            "day": dd_val,
            "month": mo or 0,
            "year": yr or 0,
        })

    if not entries:
        return []

    # Resolve year cho entries thiếu year (chỉ DD/MM)
    pending_dm: list[tuple[int, int]] = []
    for e in entries:
        if not e["year"] and e["month"]:
            pending_dm.append((e["day"], e["month"]))
    common_year = _resolve_common_year(pending_dm, today) if pending_dm else today.year

    out: list[datetime] = []
    for e in entries:
        d, mo, y = e["day"], e["month"], e["year"]
        if not mo:
            continue  # không có month → không thể tạo date
        if not y:
            y = common_year if pending_dm else _resolve_year_for_dm(d, mo, today)
        try:
            out.append(datetime(y, mo, d))
        except ValueError:
            continue

    # Sort + dedupe
    seen = set()
    uniq: list[datetime] = []
    for d in sorted(out):
        key = (d.year, d.month, d.day)
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


# ── Match text với toàn bộ rule active ───────────────────────────────────────


@lru_cache(maxsize=4)
def _get_active_rules_cached(token: int) -> list[dict[str, Any]]:
    """Lấy active rules từ DB, sort theo priority asc. Mỗi rule chỉ giữ
    primitive fields (id, pattern, output_type) để cache không giữ session."""
    from database import SessionLocal
    from models import DateFormatRule

    db = SessionLocal()
    try:
        rows = (
            db.query(DateFormatRule)
            .filter(DateFormatRule.active == True)  # noqa: E712
            .order_by(DateFormatRule.priority.asc(), DateFormatRule.id.asc())
            .all()
        )
        return [
            {
                "id": r.id,
                "pattern": r.pattern,
                "output_type": r.output_type,
                "priority": r.priority,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("load date_format_rules failed: %s", e)
        return []
    finally:
        db.close()


class _RuleProxy:
    """Mimic DateFormatRule object cho apply_rule (chỉ cần .pattern, .output_type, .id)."""

    __slots__ = ("id", "pattern", "output_type")

    def __init__(self, d: dict[str, Any]):
        self.id = d.get("id")
        self.pattern = d.get("pattern") or ""
        self.output_type = d.get("output_type") or ""


def match_text(
    text: str,
    today: datetime | None = None,
) -> tuple[list[datetime], str | None, int | None]:
    """Thử mọi active rule theo priority. Trả (dates, output_type, rule_id).

    - (dates, "dates"|"weekly"|"monthly_recurring", id): rule match + có dates
    - ([], "skip"|"verbatim", id): rule match nhưng bỏ qua tour
    - ([], None, None): không có rule nào match
    """
    if not text or not text.strip():
        return [], None, None
    rules = _get_active_rules_cached(_cache_token)
    today = today or _today()
    for rd in rules:
        proxy = _RuleProxy(rd)
        result = apply_rule(proxy, text, today)
        if result is None:
            continue
        return result, proxy.output_type.lower(), proxy.id
    return [], None, None


# ── Seed defaults ────────────────────────────────────────────────────────────

DEFAULT_RULES: list[dict[str, Any]] = [
    # priority, pattern, output_type, description
    (1, "{dd}/{mm}/{yyyy}", "dates", "DD/MM/YYYY chuẩn"),
    (2, "Khởi hành ngày {dd}/{mm}", "dates", "Khởi hành ngày DD/MM (suy năm)"),
    (3, "Tháng {mm}: {dd}, {dd}, {dd}", "dates", "Liệt kê 3 ngày trong tháng"),
    (4, "Tháng {mm}: {dd}", "dates", "1 ngày trong tháng"),
    (5, "{dd}/{mm}", "dates", "DD/MM thuần (suy năm)"),
    (6, "Tối thứ {weekday} hàng tuần", "weekly", "Recurring weekly tối"),
    (7, "Sáng thứ {weekday} hàng tuần", "weekly", "Recurring weekly sáng"),
    (8, "Chiều thứ {weekday} hàng tuần", "weekly", "Recurring weekly chiều"),
    (9, "Thứ {weekday} hàng tuần", "weekly", "Recurring weekly"),
    (10, "Thứ {weekday} và thứ {weekday} hàng tuần", "weekly", "2 weekdays"),
    (11, "Theo yêu cầu", "skip", "Skip tour: theo yêu cầu"),
    (12, "Liên hệ", "skip", "Skip tour: liên hệ"),
    (13, "Hết hạn áp dụng", "skip", "Skip tour: hết hạn"),
    (14, "Đang cập nhật", "skip", "Skip tour: đang cập nhật"),
]
# Chuyển tuple → dict cho dễ đọc
DEFAULT_RULES = [
    {"priority": p, "pattern": pat, "output_type": ot, "description": desc}
    for (p, pat, ot, desc) in DEFAULT_RULES
]


def seed_default_rules(db) -> int:
    """Insert mọi rule mặc định nếu pattern chưa có. Trả số rule mới thêm."""
    from models import DateFormatRule

    existing = {r.pattern.strip().lower() for r in db.query(DateFormatRule).all()}
    added = 0
    for rd in DEFAULT_RULES:
        key = rd["pattern"].strip().lower()
        if key in existing:
            continue
        db.add(DateFormatRule(
            pattern=rd["pattern"],
            output_type=rd["output_type"],
            priority=rd["priority"],
            description=rd["description"],
            active=True,
        ))
        existing.add(key)
        added += 1
    if added:
        db.commit()
        invalidate_date_format_cache()
    return added
