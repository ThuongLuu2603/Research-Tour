"""Phân loại thị trường / tuyến tour — đọc từ DB (Quy tắc vận hành).

Alias công ty, điểm KH, thời gian: chỉ từ bảng rules trong DB khi đã có bản ghi.
DEFAULT_* chỉ dùng khi bảng trống (môi trường mới) hoặc nút «Seed mặc định» trên UI admin.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from database import SessionLocal
from models import MarketKeywordRule, RouteKeywordRule, CompanyAliasRule, DepartureAliasRule, ScheduleAliasRule

logger = logging.getLogger(__name__)

# Fallback khi DB trống
try:
    from scrapers.market_rules import MARKET_KEYWORDS as _HARDCODED_MARKET
except ImportError:
    _HARDCODED_MARKET = {}


def _sorted_market_pairs_from_db() -> list[tuple[str, str]]:
    db = SessionLocal()
    try:
        rules = (
            db.query(MarketKeywordRule)
            .filter(MarketKeywordRule.active == True)
            .order_by(MarketKeywordRule.sort_order, MarketKeywordRule.id)
            .all()
        )
        pairs = [(r.keyword.lower().strip(), r.market) for r in rules if r.keyword.strip()]
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        return pairs
    finally:
        db.close()


def _sorted_market_pairs_fallback() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for market, keywords in _HARDCODED_MARKET.items():
        for kw in keywords:
            pairs.append((kw.lower().strip(), market))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return pairs


def _load_market_keyword_pairs() -> tuple[tuple[str, str], ...]:
    """Đọc DB mỗi lần — tránh cache process cũ trên Render multi-worker."""
    pairs = _sorted_market_pairs_from_db()
    if not pairs:
        pairs = _sorted_market_pairs_fallback()
    return tuple(pairs)


_market_kw_cache: tuple[tuple[str, str], ...] | None = None
_market_kw_cache_ts: float = 0.0
_MARKET_KW_CACHE_TTL = 300.0  # 5 phút


def _market_keyword_pairs() -> tuple[tuple[str, str], ...]:
    global _market_kw_cache, _market_kw_cache_ts
    import time
    now = time.time()
    if _market_kw_cache is not None and now - _market_kw_cache_ts < _MARKET_KW_CACHE_TTL:
        return _market_kw_cache
    _market_kw_cache = _load_market_keyword_pairs()
    _market_kw_cache_ts = now
    return _market_kw_cache


def invalidate_classification_cache() -> None:
    global _market_kw_cache, _market_kw_cache_ts, _route_matcher
    _market_kw_cache = None
    _market_kw_cache_ts = 0.0
    _company_alias_pairs.cache_clear()
    _departure_alias_pairs.cache_clear()
    _duration_alias_pairs.cache_clear()
    _schedule_alias_pairs.cache_clear()
    _load_route_rules.cache_clear()
    global _route_matcher
    _route_matcher = None
    # Throttle DELETE+INSERT ~800 route_rule_tokens rows (Render log 11:34: rebuilt mỗi
    # 2s khi user bulk delete → 24k row writes/phút → RU storm). 1 phút là đủ vì matcher
    # in-memory đã clear ngay, tokens chỉ cần đồng bộ trước query lớn tiếp theo.
    global _tokens_rebuild_last
    now_ts = _rules_time.monotonic()
    if now_ts - _tokens_rebuild_last < _TOKENS_REBUILD_THROTTLE_SEC:
        return
    _tokens_rebuild_last = now_ts
    try:
        from database import SessionLocal
        from route_rule_tokens import rebuild_route_rule_tokens

        db = SessionLocal()
        try:
            rebuild_route_rule_tokens(db)
        finally:
            db.close()
    except Exception:
        pass
    try:
        from rules_job_store import invalidate_unmatched_cache
        invalidate_unmatched_cache()
    except Exception:
        pass


def clear_tour_classified_timestamps(db, *, nguon: str | None = None) -> int:
    """Xóa dấu «đã classify» — lần «Áp dụng ngay» sau đó sẽ quét lại (kể cả khi chỉ đổi rule)."""
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    from db_retry import run_with_retry

    def _do():
        db.rollback()
        q = db.query(Tour).filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        if nguon:
            q = q.filter(Tour.nguon == nguon)
        n = q.update(
            {Tour.classified_at: None, Tour.classification_rule_id: None},
            synchronize_session=False,
        )
        db.commit()
        return int(n or 0)

    return run_with_retry(_do, db=db, label="clear-classified")


# Throttle UPDATE 8560 tour SET classified_at=NULL. Render log 2026-06-07 10:58-59:
# user bulk edit rules → invalidate_rules_changed bị gọi mỗi 5-7s → CockroachDB RU spike
# 98M/400M trong 1h (~25% monthly budget). Throttle 5 phút để chặn RU storm; UPDATE
# classified_at sẽ dồn vào lần background apply tiếp theo qua flush_pending.
import threading as _rules_threading
import time as _rules_time

_RULES_INVALIDATE_THROTTLE_SEC = 300.0  # 5 phút — đủ để bulk import xong

# Throttle riêng cho rebuild_route_rule_tokens (DELETE+INSERT ~800 rows).
_TOKENS_REBUILD_THROTTLE_SEC = 60.0
_tokens_rebuild_last = 0.0
_rules_invalidate_lock = _rules_threading.Lock()
_rules_invalidate_last_clear = 0.0
_rules_invalidate_pending_clear = False


def invalidate_rules_changed(db=None) -> None:
    """Sau khi sửa rule tuyến/thị trường — cache matcher mới + tour cần áp dụng lại.

    UPDATE classified_at trên hàng nghìn tour bị throttle 30s/lần để tránh contention.
    Lần gọi trong cửa sổ throttle chỉ set pending; flush_pending_rules_invalidate()
    sẽ catch up khi background apply chạy."""
    global _rules_invalidate_last_clear, _rules_invalidate_pending_clear

    invalidate_classification_cache()  # in-memory matcher — luôn cập nhật ngay

    now_ts = _rules_time.monotonic()
    with _rules_invalidate_lock:
        elapsed = now_ts - _rules_invalidate_last_clear
        if elapsed < _RULES_INVALIDATE_THROTTLE_SEC:
            _rules_invalidate_pending_clear = True
            return
        _rules_invalidate_last_clear = now_ts
        _rules_invalidate_pending_clear = False

    if db is None:
        db = SessionLocal()
        own = True
    else:
        own = False
    try:
        cleared = clear_tour_classified_timestamps(db)
        logger.info("Rules changed — cleared classified_at on %s tours", cleared)
    finally:
        if own:
            db.close()


def flush_pending_rules_invalidate(db=None) -> None:
    """Force clear classified_at nếu có pending từ throttle window. Gọi từ
    background apply worker để không bỏ sót UPDATE đã debounce."""
    global _rules_invalidate_last_clear, _rules_invalidate_pending_clear

    with _rules_invalidate_lock:
        if not _rules_invalidate_pending_clear:
            return
        _rules_invalidate_pending_clear = False
        _rules_invalidate_last_clear = _rules_time.monotonic()

    if db is None:
        db = SessionLocal()
        own = True
    else:
        own = False
    try:
        cleared = clear_tour_classified_timestamps(db)
        logger.info(
            "Rules changed (flushed pending) — cleared classified_at on %s tours", cleared,
        )
    finally:
        if own:
            db.close()


_route_matcher = None


def get_route_rule_matcher() -> "RouteRuleMatcher":
    from route_rule_matcher import RouteRuleMatcher

    global _route_matcher
    if _route_matcher is None:
        _route_matcher = RouteRuleMatcher(_load_route_rules())
    return _route_matcher


DEFAULT_DURATION_ALIASES: list[tuple[float, list[str]]] = [
    (0.5, ["0.5n", "0,5n", "nửa ngày", "1 buổi", "buổi"]),
    (1.0, ["1n", "1 ngày", "1n0d"]),
    (3.0, ["3n2d", "3n2đ", "3n/2d", "3 ngày 2 đêm", "3 ngày 2 dem", "3n 2d"]),
    (4.0, ["4n3d", "4n3đ", "4n/3d", "4 ngày 3 đêm", "4 ngày 3 dem", "4n 3d"]),
    (5.0, ["5n4d", "5n4đ", "5n/4d", "5 ngày 4 đêm", "5 ngày 4 dem", "5n 4d"]),
    (5.5, ["5n5d", "5n5đ", "5 ngày 5 đêm", "5n 5d"]),
    (6.0, ["6n5d", "6n5đ", "6n/5d", "6 ngày 5 đêm", "6 ngày 5 dem"]),
    (7.0, ["7n6d", "7n6đ", "7n/6d", "7 ngày 6 đêm", "7 ngày 6 dem"]),
    (8.0, ["8n7d", "8n7đ", "8n/7d", "8 ngày 7 đêm"]),
    (9.0, ["9n8d", "9n8đ", "9 ngày 8 đêm"]),
    (10.0, ["10n9d", "10n9đ", "10 ngày 9 đêm"]),
]


def _rules_table_count(model) -> int:
    db = SessionLocal()
    try:
        return db.query(model).count()
    finally:
        db.close()


def classification_rules_status() -> dict:
    from models import CompanyAliasRule, DepartureAliasRule, DurationAliasRule

    co_n = _rules_table_count(CompanyAliasRule)
    dep_n = _rules_table_count(DepartureAliasRule)
    dur_n = _rules_table_count(DurationAliasRule)
    return {
        "company": {
            "db_rules": co_n,
            "using_code_defaults": co_n == 0,
        },
        "departure": {
            "db_rules": dep_n,
            "using_code_defaults": dep_n == 0,
        },
        "duration": {
            "db_rules": dur_n,
            "using_code_defaults": dur_n == 0,
        },
        "note": "Quy tắc áp dụng toàn hệ thống (tour Main/Vietravel trong DB). Sau khi sửa, bấm «Áp dụng ngay lên tour».",
    }


@lru_cache(maxsize=1)
def _duration_alias_pairs() -> tuple[tuple[str, float], ...]:
    from models import DurationAliasRule

    db = SessionLocal()
    try:
        rules = (
            db.query(DurationAliasRule)
            .filter(DurationAliasRule.active == True)
            .order_by(DurationAliasRule.sort_order, DurationAliasRule.id)
            .all()
        )
        if rules:
            pairs = [
                (r.sort_order, len(r.alias), r.alias.lower().strip(), float(r.canonical_days))
                for r in rules
                if r.alias.strip()
            ]
            pairs.sort(key=lambda x: (x[0], -x[1]))
            return tuple((a, d) for _, _, a, d in pairs)
    finally:
        db.close()
    return _duration_pairs_from_defaults()


def _duration_pairs_from_defaults() -> tuple[tuple[str, float], ...]:
    pairs = []
    for days, aliases in DEFAULT_DURATION_ALIASES:
        for a in aliases:
            pairs.append((0, len(a), a.lower().strip(), days))
    pairs.sort(key=lambda x: (x[0], -x[1]))
    return tuple((a, d) for _, _, a, d in pairs)


def seed_duration_aliases_from_defaults() -> int:
    from models import DurationAliasRule
    from db_retry import run_with_retry

    def _do():
        db = SessionLocal()  # phiên mới mỗi lần thử; count-check → idempotent
        try:
            if db.query(DurationAliasRule).count() > 0:
                return 0
            order = 0
            for days, aliases in DEFAULT_DURATION_ALIASES:
                for a in aliases:
                    db.add(DurationAliasRule(canonical_days=days, alias=a, sort_order=order))
                    order += 1
            db.commit()
            return order
        finally:
            db.close()

    n = run_with_retry(_do, label="seed-duration-aliases")
    if n:
        invalidate_classification_cache()
    return n


def _canonical_tour_query(db):
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    return db.query(Tour).filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))


def _apply_route_state_filter(q, route_state: str | None):
    """empty = chưa có tuyến (bảng vàng); filled = đã có tuyến — điều chỉnh lại."""
    from sqlalchemy import func, or_

    from models import Tour

    if route_state == "empty":
        return q.filter(
            or_(
                Tour.tuyen_tour.is_(None),
                Tour.tuyen_tour == "",
                func.trim(Tour.tuyen_tour) == "",
            )
        )
    if route_state == "filled":
        return q.filter(
            Tour.tuyen_tour.isnot(None),
            Tour.tuyen_tour != "",
            func.trim(Tour.tuyen_tour) != "",
        )
    return q


def _apply_incremental_filter(q):
    """Chỉ tour chưa qua «Áp dụng ngay» hoặc dữ liệu đổi sau lần đó (± vài giây commit)."""
    from datetime import timedelta

    from sqlalchemy import and_, or_

    from models import Tour

    slack = timedelta(seconds=10)
    return q.filter(
        or_(
            Tour.classified_at.is_(None),
            and_(
                Tour.classified_at.isnot(None),
                Tour.updated_at > Tour.classified_at + slack,
            ),
        )
    )


def count_canonical_tours(db, *, incremental: bool = False) -> int:
    q = _canonical_tour_query(db)
    if incremental:
        q = _apply_incremental_filter(q)
    return q.count()


def _iter_canonical_tour_batches(
    db,
    batch_size: int = 500,
    *,
    keyword_filter: list[str] | None = None,
    route_state: str | None = None,
    incremental: bool = False,
    start_after_id: int = 0,
):
    """Phân trang theo id — chỉ cột cần cho apply rule."""
    from sqlalchemy.orm import load_only

    from models import Tour

    cols = load_only(
        Tour.id,
        Tour.ten_tour,
        Tour.ma_tour,
        Tour.lich_trinh,
        Tour.thi_truong,
        Tour.tuyen_tour,
        Tour.cong_ty,
        Tour.diem_kh,
        Tour.thoi_gian,
        Tour.so_ngay,
        Tour.link_url,
        Tour.classification_rule_id,
        Tour.classified_at,
        Tour.segment_key,
        Tour.search_text,
        Tour.manual_locked,   # cần để bỏ qua tour admin đã khóa tay
    )
    last_id = max(0, int(start_after_id or 0))
    while True:
        q = (
            _canonical_tour_query(db)
            .options(cols)
            .filter(Tour.id > last_id)
            .order_by(Tour.id)
        )
        q = _apply_route_state_filter(q, route_state)
        if incremental:
            q = _apply_incremental_filter(q)
        if keyword_filter:
            from tour_search import apply_keyword_prefilter

            q = apply_keyword_prefilter(q, keyword_filter)
        rows = q.limit(batch_size).all()
        if not rows:
            break
        yield rows
        last_id = rows[-1].id


def apply_duration_aliases_to_tours(db) -> int:
    from db_retry import run_with_retry

    count = 0
    for batch in _iter_canonical_tour_batches(db):
        def _do(b=batch):
            db.rollback()  # lô đã commit trước vẫn còn; lô này re-apply sau rollback
            n = 0
            for t in b:
                if getattr(t, "manual_locked", False):
                    continue  # admin khóa tay Thời gian → không ghi đè
                new_tg, new_sn = normalize_duration_text(t.thoi_gian, t.so_ngay)
                changed = False
                if new_sn is not None and (not t.so_ngay or float(t.so_ngay) != new_sn):
                    t.so_ngay = new_sn
                    changed = True
                # Ghi đè text về dạng chuẩn NĐ khi khớp (giữ raw nếu không khớp).
                if new_tg and new_tg != (t.thoi_gian or ""):
                    t.thoi_gian = new_tg[:64]
                    changed = True
                if changed:
                    n += 1
            db.commit()
            return n

        count += run_with_retry(_do, db=db, label="duration-aliases-batch")
    return count


def is_company_alias_matched(raw_name: str) -> bool:
    lower = (raw_name or "").strip().lower()
    if not lower:
        return False
    for alias, _canonical in _company_alias_pairs():
        if _alias_matches_text(alias, lower):
            return True
    return False


def is_departure_alias_matched(raw: str) -> bool:
    return _match_departure_alias(raw) is not None


def is_schedule_alias_matched(raw: str) -> bool:
    """Lich_kh có khớp một alias trong bảng schedule_alias_rules không.

    True = text đã được map về canonical (kể cả canonical="" = bỏ qua) → không
    đưa vào panel «chưa khớp» nữa."""
    return _match_schedule_alias(raw) is not None


def is_duration_alias_matched(thoi_gian: str, so_ngay: float | None) -> bool:
    if so_ngay and 0 < so_ngay <= 45:
        return True
    text = re.sub(r"\s+", " ", (thoi_gian or "").strip().lower())
    if not text:
        return False
    for alias, _days in _duration_alias_pairs():
        if alias == text or alias in text:
            return True
    return False


def is_duration_text_alias_matched(thoi_gian: str) -> bool:
    """Text thời gian đã được chuẩn hóa chưa — CHỈ xét text, KHÔNG xét so_ngay.

    Dùng cho panel «Chưa khớp» tab Thời gian: tour có so_ngay parse được (vd
    "9 ngày 8 đêm" → 9 qua parse_ngay) vẫn cần hiện text raw nếu chưa có alias
    trong DurationAliasRule để admin chuẩn hóa. Matched khi:
      - text khớp alias chính thức (DurationAliasRule), HOẶC
      - text đã đúng định dạng NĐ chuẩn (parse_duration_nd: 5N4Đ, 1N, 0.5N...).
    """
    from duration_format import parse_duration_nd

    text = re.sub(r"\s+", " ", (thoi_gian or "").strip().lower())
    if not text:
        return False
    for alias, _days in _duration_alias_pairs():
        if alias == text or alias in text:
            return True
    return parse_duration_nd(text.replace(" ", "")) is not None


def resolve_duration_days(thoi_gian: str, so_ngay: float | None) -> tuple[float | None, bool]:
    """Trả về (số ngày chuẩn, đã khớp alias/so_ngay). NĐ: 5N4Đ→5, 5N5Đ→5.5, 0.5N→0.5."""
    from duration_format import parse_duration_nd

    if so_ngay and 0 < so_ngay <= 45:
        return round(float(so_ngay), 1), True
    text = re.sub(r"\s+", " ", (thoi_gian or "").strip().lower())
    if text:
        for alias, days in _duration_alias_pairs():
            if alias == text or alias in text:
                return days, True
        parsed = parse_duration_nd(text.replace(" ", ""))
        if parsed is not None:
            return parsed, False
    if not thoi_gian:
        return None, False
    s = thoi_gian.strip().lower()
    parsed = parse_duration_nd(s)
    if parsed is not None:
        return parsed, False
    m = re.search(r"(\d+)\s*ngày", s)
    if m:
        d = float(m.group(1))
        return (d, False) if 0 < d <= 45 else (None, False)
    return None, False


def normalize_duration_text(thoi_gian: str, so_ngay: float | None) -> tuple[str, float | None]:
    """Chuẩn hóa thời gian → nhãn NĐ chuẩn (vd '7 ngày 6 đêm' → '7N6Đ') khi KHỚP
    Quy tắc phân loại; GIỮ raw nếu không khớp (TUYỆT ĐỐI không trả rỗng).

    Trả (text_chuẩn, so_ngay). Dùng khi ghi DB để cột Thời gian trong Sản phẩm &
    Data hiển thị đúng dạng chuẩn như tab «Thời gian» của Quy tắc phân loại.
    """
    days, matched = resolve_duration_days(thoi_gian or "", so_ngay)
    if days is not None and matched and 0 < days <= 45:
        from duration_format import format_duration_label
        label = format_duration_label(days)
        if label and label != "—":
            return label, round(float(days), 1)
    return (thoi_gian or ""), so_ngay


def _tour_title_hint(t) -> str:
    return re.sub(r"\s+", " ", (t.ten_tour or "").strip())[:120]


_TITLE_KEYWORD_HINTS: tuple[str, ...] = (
    "bangkok", "pattaya", "phuket", "chiang mai", "thái lan", "thailand",
    "nhật bản", "tokyo", "osaka", "đài loan", "taiwan", "singapore", "malaysia",
    "hàn quốc", "seoul", "trung quốc", "châu âu", "paris", "dubai", "mexico",
    "canada", "cuba", "houston", "esim", "voucher",
)


def suggest_keyword_from_title(title: str) -> str:
    """Gợi ý 1 keyword ngắn từ tên tour (địa danh / sản phẩm)."""
    entry = _market_unmatched_entry(title)
    kw = entry.get("keyword") or ""
    if kw:
        return kw
    s = (title or "").lower()
    best = ""
    for h in _TITLE_KEYWORD_HINTS:
        if h in s and len(h) > len(best):
            best = h
    return best


def merge_keyword_csv(existing: str, add: str) -> str:
    seen: list[str] = []
    for blob in (existing, add):
        for part in blob.split(","):
            p = part.strip().lower()
            if p and p not in seen:
                seen.append(p)
    return ", ".join(seen)


# Từ quá chung — không dùng làm keyword gom nhóm (gây gán sai thị trường).
_MARKET_HINT_STOPWORDS = frozenset({
    "tour", "tours", "du", "lich", "lịch", "chua", "chưa", "hang", "hành", "hanh", "trinh", "trình",
    "kham", "khám", "pha", "phá", "trai", "trải", "nghiem", "nghiệm", "triệu", "triệu", "dong", "đồng",
    "ngay", "ngày", "dem", "đêm", "khoi", "khởi", "tai", "tại", "tu", "từ", "voi", "với", "theo", "cua", "của",
    "va", "và", "mien", "miền", "trung", "bac", "bắc", "nam", "viet", "việt", "nam", "kham", "phá",
    "trải", "nghiệm", "chỉ", "chi", "có", "co", "gia", "giá", "tạm", "tam", "chưa", "co", "có",
    "hành", "trình", "khám", "phá", "trải", "nghiệm", "combo", "package", "combo",
})

_PRODUCT_MARKET_HINTS: tuple[tuple[str, str, str], ...] = (
    ("esim", "esim", "Esim"),
    ("e-sim", "esim", "Esim"),
    ("voucher", "voucher", "Voucher"),
    ("cruise", "cruise", "Cruise"),
)

# Địa danh → gợi ý thị trường (keyword nên thêm vào rule).
_PLACE_MARKET_HINTS: tuple[tuple[str, str, str], ...] = (
    ("thái lan", "thái lan", "Thái Lan"),
    ("thailand", "thailand", "Thái Lan"),
    ("bangkok", "bangkok", "Thái Lan"),
    ("pattaya", "pattaya", "Thái Lan"),
    ("phuket", "phuket", "Thái Lan"),
    ("nhật bản", "nhật bản", "Nhật Bản"),
    ("nhật ban", "nhật bản", "Nhật Bản"),
    ("japan", "japan", "Nhật Bản"),
    ("tokyo", "tokyo", "Nhật Bản"),
    ("osaka", "osaka", "Nhật Bản"),
    ("đài loan", "đài loan", "Đài Loan"),
    ("dai loan", "đài loan", "Đài Loan"),
    ("taiwan", "taiwan", "Đài Loan"),
    ("singapore", "singapore", "Singapore - Malaysia"),
    ("malaysia", "malaysia", "Singapore - Malaysia"),
    ("hàn quốc", "hàn quốc", "Hàn Quốc"),
    ("han quoc", "hàn quốc", "Hàn Quốc"),
    ("korea", "korea", "Hàn Quốc"),
    ("seoul", "seoul", "Hàn Quốc"),
    ("trung quốc", "trung quốc", "Trung Quốc"),
    ("china", "china", "Trung Quốc"),
    ("bắc kinh", "bắc kinh", "Trung Quốc"),
    ("thượng hải", "thượng hải", "Trung Quốc"),
    ("châu âu", "châu âu", "Châu Âu"),
    ("chau au", "châu âu", "Châu Âu"),
    ("europe", "europe", "Châu Âu"),
    ("paris", "paris", "Châu Âu"),
    ("úc", "úc", "Úc"),
    ("australia", "australia", "Úc"),
    ("new zealand", "new zealand", "Úc"),
    ("mỹ", "mỹ", "Mỹ"),
    ("my", "mỹ", "Mỹ"),
    ("usa", "usa", "Mỹ"),
    ("dubai", "dubai", "Trung Đông"),
    ("turkey", "turkey", "Thổ Nhĩ Kỳ"),
    ("thổ nhĩ kỳ", "thổ nhĩ kỳ", "Thổ Nhĩ Kỳ"),
    ("ai cập", "ai cập", "Ai Cập"),
    ("campuchia", "campuchia", "Campuchia"),
    ("cambodia", "cambodia", "Campuchia"),
    ("lào", "lào", "Lào"),
    ("indonesia", "indonesia", "Indonesia"),
    ("bali", "bali", "Indonesia"),
)


def _market_unmatched_entry(title: str) -> dict:
    """
    Phân tích tour chưa khớp thị trường.
    Chỉ gom nhóm khi có keyword đặc thù (địa danh / esim / voucher…).
    Còn lại: mỗi tên tour là một dòng — tránh gom theo «tour», «lịch»…
    """
    s = (title or "").lower()
    for needle, keyword, market in _PRODUCT_MARKET_HINTS:
        if needle in s:
            return {
                "bucket_key": f"kw:{keyword}",
                "keyword": keyword,
                "suggested_market": market,
                "grouped": True,
            }
    for needle, keyword, market in sorted(_PLACE_MARKET_HINTS, key=lambda x: -len(x[0])):
        if needle in s:
            return {
                "bucket_key": f"kw:{keyword}",
                "keyword": keyword,
                "suggested_market": market,
                "grouped": True,
            }
    tokens = re.findall(r"[a-zA-ZÀ-ỹ0-9]{3,}", title or "")
    specific = [
        t.lower()
        for t in tokens
        if len(t) >= 4 and t.lower() not in _MARKET_HINT_STOPWORDS
    ]
    if specific:
        kw = max(specific, key=len)
        return {
            "bucket_key": f"kw:{kw}",
            "keyword": kw,
            "suggested_market": "",
            "grouped": True,
        }
    norm = re.sub(r"\s+", " ", (title or "").strip())[:100]
    return {
        "bucket_key": f"t:{norm}",
        "keyword": "",
        "suggested_market": "",
        "grouped": False,
    }


def is_market_rule_matched(
    ten_tour: str,
    lich_trinh: str = "",
    *,
    market_pairs: tuple[tuple[str, str], ...] | None = None,
    route_rules: tuple[tuple[str, str, tuple[str, ...]], ...] | None = None,
) -> bool:
    """Đã khớp phân loại = có rule tuyến (thị trường suy ra từ rule, không dùng keyword TT)."""
    _ = market_pairs  # legacy callers
    _, _, from_route = resolve_market_and_route(
        ten_tour or "",
        lich_trinh or "",
        route_rules=route_rules,
    )
    return from_route


def is_route_rule_matched(thi_truong: str, ten_tour: str, lich_trinh: str = "") -> bool:
    _ = thi_truong
    _, _, from_route_rule = resolve_market_and_route(ten_tour or "", lich_trinh or "")
    return from_route_rule


def _unmatched_add_member(bucket: dict, title: str) -> None:
    members: dict[str, int] = bucket.setdefault("_members", {})
    members[title] = members.get(title, 0) + 1
    bucket["count"] = bucket.get("count", 0) + 1


def _unmatched_members_list(bucket: dict, *, limit: int = 40) -> list[dict]:
    raw: dict[str, int] = bucket.get("_members") or {}
    return [
        {"title": t, "count": c}
        for t, c in sorted(raw.items(), key=lambda x: (-x[1], x[0]))[:limit]
    ]


def collect_classify_gaps(db) -> list[dict]:
    """
    Tour chưa có tuyến (cột DB trống) — không quét lại toàn bộ DB bằng resolve_market_and_route.
    Dùng cho bảng vàng «Tour chưa khớp tuyến» trên admin.
    """
    from sqlalchemy import func, or_

    from data_sources import DB_CANONICAL_NGUON
    from models import Tour
    from tour_stats_exclusions import apply_stats_exclusion_query

    q = (
        db.query(Tour.id, Tour.ten_tour, Tour.thi_truong, Tour.lich_trinh)
        .filter(Tour.nguon.in_(tuple(DB_CANONICAL_NGUON)))
        .filter(
            or_(
                Tour.tuyen_tour.is_(None),
                Tour.tuyen_tour == "",
                func.trim(Tour.tuyen_tour) == "",
            )
        )
    )
    q = apply_stats_exclusion_query(q)

    matcher = get_route_rule_matcher()
    healed_ids: list[int] = []
    classify_gaps: dict[str, dict] = {}
    for tour_id, ten_tour, thi_truong, lich_trinh in q.yield_per(500):
        if len(healed_ids) >= 800:
            break
        title = re.sub(r"\s+", " ", (ten_tour or "").strip())[:120]
        if not title:
            continue
        mk, rt, from_rule, rule_id = matcher.resolve(ten_tour or "", lich_trinh or "")
        if from_rule:
            tour = db.query(Tour).filter(Tour.id == tour_id).first()
            if tour:
                m_delta, r_delta = _apply_rule_result_to_tour(tour, mk, rt, True, rule_id)
                if m_delta or r_delta:
                    healed_ids.append(tour_id)
            continue
        stored_mk = (thi_truong or "").strip()
        if stored_mk in ("Khác",):
            stored_mk = ""
        skw = suggest_keyword_from_title(title)
        hint = _market_unmatched_entry(title)
        sug_mk = stored_mk or (hint.get("suggested_market") or "")
        if title not in classify_gaps:
            classify_gaps[title] = {
                "value": title,
                "count": 0,
                "sample": title,
                "needs_market": False,
                "needs_route": True,
                "suggested_market": sug_mk,
                "suggested_route": sug_mk or "",
                "route_keywords": skw,
                "resolved_market": stored_mk,
            }
        classify_gaps[title]["count"] += 1

    if healed_ids:
        # Heal cơ hội trong 1 thao tác ĐỌC → commit best-effort: lỗi tạm thời không làm hỏng
        # bảng gaps (lần xem sau sẽ heal lại). Không để 1 WriteTooOld phá cả màn hình.
        try:
            db.commit()
            from tour_search import sync_search_tsv_for_ids

            sync_search_tsv_for_ids(healed_ids)
        except Exception:
            db.rollback()

    return sorted(
        [
            {
                "value": k,
                "count": v["count"],
                "sample": v.get("sample", k),
                "needs_market": bool(v.get("needs_market")),
                "needs_route": bool(v.get("needs_route")),
                "suggested_market": v.get("suggested_market") or "",
                "suggested_route": v.get("suggested_route") or "",
                "market_keyword": v.get("market_keyword") or "",
                "route_keywords": v.get("route_keywords") or "",
                "resolved_market": v.get("resolved_market") or "",
            }
            for k, v in classify_gaps.items()
        ],
        key=lambda x: -x["count"],
    )[:200]


def collect_unmatched_values(tours: list, *, vtr_only: bool = True) -> dict:
    """Giá trị tour chưa khớp quy tắc — dùng gán keyword/alias trên UI admin."""
    from data_sources import DB_CANONICAL_NGUON
    from tour_sources import is_vietravel_tab
    from tour_stats_exclusions import is_stats_excluded_tour

    cong_ty: dict[str, int] = {}
    diem_kh: dict[str, int] = {}
    thoi_gian: dict[str, int] = {}
    lich_kh: dict[str, int] = {}
    thi_truong: dict[str, dict] = {}
    tuyen_tour: dict[str, dict] = {}
    classify_gaps: dict[str, dict] = {}

    # Import muộn để tránh import vòng nếu departure_parser import classification.
    from departure_parser import parse_departure_dates

    matcher = get_route_rule_matcher()
    for t in tours:
        if vtr_only and not is_vietravel_tab(t):
            continue

        # Alias mapping (company/departure/duration) gom CẢ tour FindTourGo + tour bị
        # stats_excluded. User cần map alias cho mọi nguồn, không chỉ Main+Vietravel.
        # Trước đây canonical filter cắt mất "CU CHI TUNNELS" và các diem_kh lạ từ FTG.
        raw_co_for_alias = (t.cong_ty or "").strip()
        if raw_co_for_alias and not is_company_alias_matched(raw_co_for_alias):
            cong_ty[raw_co_for_alias] = cong_ty.get(raw_co_for_alias, 0) + 1
        raw_dep_for_alias = (t.diem_kh or "").strip()
        if raw_dep_for_alias and not is_departure_alias_matched(raw_dep_for_alias):
            diem_kh[raw_dep_for_alias] = diem_kh.get(raw_dep_for_alias, 0) + 1
        raw_tg_for_alias = (t.thoi_gian or "").strip()
        if raw_tg_for_alias:
            # CHỈ xét text vs DurationAliasRule / định dạng NĐ chuẩn. Trước đây dùng
            # resolve_duration_days(text, so_ngay) — so_ngay parse được (vd "9 ngày
            # 8 đêm" → 9) bị coi là matched → panel «Chưa khớp» tab Thời gian luôn
            # rỗng, admin không thấy text raw cần chuẩn hóa alias.
            if not is_duration_text_alias_matched(raw_tg_for_alias):
                thoi_gian[raw_tg_for_alias] = thoi_gian.get(raw_tg_for_alias, 0) + 1
        else:
            # Không có text: chỉ flag khi so_ngay cũng không dùng được.
            days_for_alias, _ = resolve_duration_days("", t.so_ngay)
            if days_for_alias is None:
                key = f"so_ngay={t.so_ngay}" if t.so_ngay else "—"
                thoi_gian[key] = thoi_gian.get(key, 0) + 1

        # Ngày KH (lich_kh): gom giá trị chưa được DSL DateFormatRule match.
        # Trước đây gate bằng parse_departure_dates() (hardcoded fallback) → bị "cứu"
        # bởi parser cũ, panel "Chưa khớp" luôn rỗng dù DSL không match.
        # Giờ gate bằng match_text() từ DSL — chuỗi nào DSL không match sẽ vào panel,
        # admin có thể viết rule mới cho chúng.
        raw_lkh = (t.lich_kh or "").strip()
        if raw_lkh:
            try:
                from date_format_rules import match_text as _dfr_match_text
                _dfr_dates, _dfr_ot, _dfr_rid = _dfr_match_text(raw_lkh)
                dsl_matched = _dfr_ot is not None
            except Exception:
                dsl_matched = False
            if not dsl_matched and not is_schedule_alias_matched(raw_lkh):
                lich_kh[raw_lkh] = lich_kh.get(raw_lkh, 0) + 1

        # Classify (market/route) chỉ áp dụng cho Main+Vietravel — FTG dùng sheet riêng
        # nên không tham gia route_keyword_rules. Skip nếu không canonical hoặc excluded.
        if getattr(t, "nguon", None) not in DB_CANONICAL_NGUON:
            continue
        if is_stats_excluded_tour(t):
            continue
        title = _tour_title_hint(t)
        market, route, from_route_rule, _rule_id = matcher.resolve(
            t.ten_tour or "",
            t.lich_trinh or "",
        )
        stored_mk = (t.thi_truong or "").strip()
        if title and not from_route_rule:
            skw = suggest_keyword_from_title(title)
            hint = _market_unmatched_entry(title)
            sug_mk = (
                stored_mk
                if stored_mk and stored_mk not in ("Khác",)
                else (hint.get("suggested_market") or "")
            )
            if title not in classify_gaps:
                classify_gaps[title] = {
                    "value": title,
                    "count": 0,
                    "sample": title,
                    "needs_market": False,
                    "needs_route": True,
                    "suggested_market": sug_mk,
                    "suggested_route": route if route not in ("", "Khác") else sug_mk or "",
                    "route_keywords": skw,
                    "resolved_market": stored_mk if stored_mk not in ("", "Khác") else "",
                }
            classify_gaps[title]["count"] += 1
            if title not in tuyen_tour:
                tuyen_tour[title] = {
                    "count": 0,
                    "thi_truong": stored_mk or sug_mk or "",
                    "sample": title,
                    "suggested_thi_truong": sug_mk,
                    "bucket_key": f"route:{title}",
                }
            _unmatched_add_member(tuyen_tour[title], title)

        # Đã gom company/departure/duration aliases ở đầu loop (cho mọi nguồn) — không
        # lặp lại ở đây để tránh double-count.

    def _rows(d: dict[str, int]) -> list[dict]:
        # Trước đây cap [:40] — user nhập alias cho rule mới + có hàng trăm value
        # khác chưa khớp → 40 dòng đầu mất hết, panel "Chưa khớp" trông trống.
        # Bump lên 500: đủ rộng cho thực tế nhưng vẫn có ceiling an toàn.
        return sorted([{"value": k, "count": v} for k, v in d.items()], key=lambda x: -x["count"])[:500]

    market_rows = sorted(
        [
            {
                "value": k,
                "count": v["count"],
                "sample": v.get("sample", k),
                "keyword": v.get("keyword") or "",
                "suggested_market": v.get("suggested_market") or "",
                "grouped": False,
                "bucket_key": v.get("bucket_key") or f"market:{k}",
                "members": _unmatched_members_list(v),
            }
            for k, v in thi_truong.items()
        ],
        key=lambda x: -x["count"],
    )[:500]  # bump từ 40 — xem điều chỉnh ceiling trong _rows()
    route_rows = sorted(
        [
            {
                "value": k,
                "count": v["count"],
                "thi_truong": v["thi_truong"],
                "sample": v.get("sample", k),
                "suggested_thi_truong": v.get("suggested_thi_truong") or "",
                "bucket_key": v.get("bucket_key") or f"route:{k}",
                "grouped": v["count"] > 1,
                "members": _unmatched_members_list(v),
            }
            for k, v in tuyen_tour.items()
        ],
        key=lambda x: -x["count"],
    )[:500]

    classify_rows = sorted(
        [
            {
                "value": k,
                "count": v["count"],
                "sample": v.get("sample", k),
                "needs_market": bool(v.get("needs_market")),
                "needs_route": bool(v.get("needs_route")),
                "suggested_market": v.get("suggested_market") or "",
                "suggested_route": v.get("suggested_route") or "",
                "market_keyword": v.get("market_keyword") or "",
                "route_keywords": v.get("route_keywords") or "",
                "resolved_market": v.get("resolved_market") or "",
            }
            for k, v in classify_gaps.items()
        ],
        key=lambda x: -x["count"],
    )[:500]

    return {
        "thi_truong": market_rows,
        "tuyen_tour": route_rows,
        "classify": classify_rows,
        "cong_ty": _rows(cong_ty),
        "diem_kh": _rows(diem_kh),
        "thoi_gian": _rows(thoi_gian),
        "lich_kh": _rows(lich_kh),
    }


DEFAULT_COMPANY_ALIASES: list[tuple[str, list[str]]] = [
    ("Vietravel", ["vietravel", "travel.com.vn", "cong ty co phan vietravel"]),
    ("Saigontourist", ["saigontourist", "sai gon tourist", "sgt"]),
    ("Fiditour", ["fiditour", "fidi tour"]),
    ("Tugo", ["tugo", "tu go"]),
    ("Hanoitourist", ["hanoitourist", "ha noi tourist"]),
    ("Ben Thanh Tourist", ["ben thanh tourist", "benthancorp", "ben thanh"]),
    ("Transviet", ["transviet", "trans viet"]),
    ("Luxury Travel", ["luxury travel", "luxurytravel"]),
]


def _company_pairs_from_defaults() -> tuple[tuple[str, str], ...]:
    pairs = []
    for canonical, aliases in DEFAULT_COMPANY_ALIASES:
        for a in aliases:
            pairs.append((0, len(a), a.lower().strip(), canonical))
    pairs.sort(key=lambda x: (x[0], -x[1]))
    return tuple((a, c) for _, _, a, c in pairs)


@lru_cache(maxsize=1)
def _company_alias_pairs() -> tuple[tuple[str, str], ...]:
    db = SessionLocal()
    try:
        rules = (
            db.query(CompanyAliasRule)
            .filter(CompanyAliasRule.active == True)
            .order_by(CompanyAliasRule.sort_order, CompanyAliasRule.id)
            .all()
        )
        if rules:
            pairs = [
                (r.sort_order, len(r.alias), r.alias.lower().strip(), r.canonical_name.strip())
                for r in rules
                if r.alias.strip()
            ]
            pairs.sort(key=lambda x: (x[0], -x[1]))
            return tuple((a, c) for _, _, a, c in pairs)
    finally:
        db.close()
    return _company_pairs_from_defaults()


def _alias_matches_text(alias: str, lower: str) -> bool:
    """Khớp alias trong chuỗi — ưu tiên khớp chính xác; substring cần đủ dài."""
    if alias == lower:
        return True
    if len(alias) < 8 or alias not in lower:
        return False
    if len(alias) >= 14:
        return True
    return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", lower))


def resolve_company_name(raw_name: str) -> str:
    """Chuẩn hóa tên công ty — chỉ theo Quy tắc vận hành (DB), sort_order trước."""
    s = (raw_name or "").strip()
    if not s:
        return ""
    lower = s.lower()
    pairs = _company_alias_pairs()
    for alias, canonical in pairs:
        if alias == lower:
            return canonical
    for alias, canonical in pairs:
        if _alias_matches_text(alias, lower):
            return canonical
    return s


def seed_company_aliases_from_defaults() -> int:
    from db_retry import run_with_retry

    def _do():
        db = SessionLocal()
        try:
            if db.query(CompanyAliasRule).count() > 0:
                return 0
            order = 0
            for canonical, aliases in DEFAULT_COMPANY_ALIASES:
                for a in aliases:
                    db.add(CompanyAliasRule(canonical_name=canonical, alias=a, sort_order=order))
                    order += 1
            db.commit()
            return order
        finally:
            db.close()

    n = run_with_retry(_do, label="seed-company-aliases")
    if n:
        invalidate_classification_cache()
    return n


def apply_company_aliases_to_tours(db) -> int:
    from db_retry import run_with_retry

    count = 0
    for batch in _iter_canonical_tour_batches(db):
        def _do(b=batch):
            db.rollback()
            n = 0
            for t in b:
                resolved = resolve_company_name(t.cong_ty)
                if resolved and resolved != (t.cong_ty or ""):
                    t.cong_ty = resolved[:256]
                    n += 1
            db.commit()
            return n

        count += run_with_retry(_do, db=db, label="company-aliases-batch")
    return count


DEFAULT_DEPARTURE_ALIASES: list[tuple[str, list[str]]] = [
    ("TP.HCM", ["hồ chí minh", "tp.hcm", "tp hcm", "sài gòn", "sai gon", "tphcm", "hcm", "sgn", "tân sơn nhất"]),
    ("Hà Nội", ["hà nội", "ha noi", "hn", "nội bài", "noi bai"]),
    ("Đà Nẵng", ["đà nẵng", "da nang", "dng"]),
    ("Cần Thơ", ["cần thơ", "can tho"]),
    ("Nha Trang", ["nha trang", "cam ranh"]),
    ("Huế", ["huế", "hue", "phú bài"]),
    ("Hải Phòng", ["hải phòng", "hai phong", "hp"]),
    ("Vinh", ["vinh", "nghệ an", "nghe an"]),
    ("Phú Quốc", ["phú quốc", "phu quoc"]),
    ("Đà Lạt", ["đà lạt", "da lat", "lâm đồng", "lam dong"]),
    ("Quy Nhon", ["quy nhon", "quy nhơn", "bình định"]),
    ("Pleiku", ["pleiku", "gia lai"]),
    ("Buôn Ma Thuột", ["buôn ma thuột", "buon ma thuot", "dak lak"]),
]


def _departure_pairs_from_defaults() -> tuple[tuple[str, str], ...]:
    pairs = []
    for canonical, aliases in DEFAULT_DEPARTURE_ALIASES:
        for a in aliases:
            pairs.append((0, len(a), a.lower().strip(), canonical))
    pairs.sort(key=lambda x: (x[0], -x[1]))
    return tuple((a, c) for _, _, a, c in pairs)


@lru_cache(maxsize=1)
def _departure_alias_pairs() -> tuple[tuple[str, str], ...]:
    db = SessionLocal()
    try:
        rules = (
            db.query(DepartureAliasRule)
            .filter(DepartureAliasRule.active == True)
            .order_by(DepartureAliasRule.sort_order, DepartureAliasRule.id)
            .all()
        )
        if rules:
            pairs = [
                (r.sort_order, len(r.alias), r.alias.lower().strip(), r.canonical_name.strip())
                for r in rules
                if r.alias.strip()
            ]
            pairs.sort(key=lambda x: (x[0], -x[1]))
            return tuple((a, c) for _, _, a, c in pairs)
    finally:
        db.close()
    return _departure_pairs_from_defaults()


def _match_departure_alias(text: str) -> str | None:
    lower = (text or "").strip().lower()
    if not lower:
        return None
    for alias, canonical in _departure_alias_pairs():
        if alias == lower:
            return canonical
    for alias, canonical in _departure_alias_pairs():
        if _alias_matches_text(alias, lower):
            return canonical
    return None


def resolve_departure_point(raw: str) -> str:
    """Chuẩn hóa điểm khởi hành từ alias → tên chính thức.

    PRESERVE RAW khi raw chứa multi-segment indicators:
      ✈, →, ←, |   ← multi-leg journey separators
      Hoặc có ≥ 2 phần khi split bằng dash → tour multi-điểm.

    Lý do: alias substring match (vd "TP. Hồ Chí Minh" len ≥ 8) sẽ ăn vào
    "TP. HỒ CHÍ MINH ✈ LỆ GIANG" → trả canonical → strip "✈ LỆ GIANG" → mất
    thông tin. User không thấy raw trong panel "Chưa khớp alias" để map.
    Giữ raw cho user manual map sau.

    Cho single-segment (vd "Sài Gòn", "ĐÀ LẠT"): vẫn alias match như cũ.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # Multi-leg indicators — preserve raw, không auto-resolve
    if any(sep in s for sep in ("✈", "→", "←", "|")):
        return s[:256]
    # Multi-segment dash: "A - B - C" với ≥ 2 phần text có nghĩa → preserve raw
    dash_parts = [p.strip() for p in re.split(r"[\-–—]", s) if p.strip() and len(p.strip()) >= 3]
    if len(dash_parts) >= 2:
        return s[:256]

    matched = _match_departure_alias(s)
    if matched:
        return matched
    head = re.split(r"[,|\-–—/]", s)[0].strip()
    if head and head != s:
        matched = _match_departure_alias(head)
        if matched:
            return matched
        return head[:256]
    return s[:256]


def seed_departure_aliases_from_defaults() -> int:
    from db_retry import run_with_retry

    def _do():
        db = SessionLocal()
        try:
            if db.query(DepartureAliasRule).count() > 0:
                return 0
            order = 0
            for canonical, aliases in DEFAULT_DEPARTURE_ALIASES:
                for a in aliases:
                    db.add(DepartureAliasRule(canonical_name=canonical, alias=a, sort_order=order))
                    order += 1
            db.commit()
            return order
        finally:
            db.close()

    n = run_with_retry(_do, label="seed-departure-aliases")
    if n:
        invalidate_classification_cache()
    return n


def apply_departure_aliases_to_tours(db) -> int:
    from db_retry import run_with_retry

    count = 0
    for batch in _iter_canonical_tour_batches(db):
        def _do(b=batch):
            db.rollback()
            n = 0
            for t in b:
                resolved = resolve_departure_point(t.diem_kh)
                if resolved and resolved != (t.diem_kh or ""):
                    t.diem_kh = resolved[:256]
                    n += 1
            db.commit()
            return n

        count += run_with_retry(_do, db=db, label="departure-aliases-batch")
    return count


def apply_alias_rule_targeted(db, kind: str, alias: str, *, cap: int = 2000) -> dict:
    """Targeted apply NGAY sau khi gán alias — KHÔNG full scan (UX: tour hiệu lực tức thì).

    Chỉ load tour có field chứa alias (ILIKE %alias%, cap ``cap`` row) rồi chạy đúng
    resolver per-tour (resolve_company_name / resolve_departure_point /
    resolve_duration_days) → tái dùng nguyên logic full apply (multi-leg preserve,
    sticky, alias ordering) — không lệch kết quả.

    kind: "company" | "departure" | "duration" (schedule không ghi field tour).
    Sticky: chỉ ghi khi resolved non-empty và != giá trị cũ.
    manual_locked: thoi_gian/so_ngay bị khóa tay → SKIP (cùng design
    _apply_rule_result_to_tour); cong_ty/diem_kh không thuộc phạm vi khóa.

    Trả {"applied": N, "candidates": M, "capped": bool} — capped=True nghĩa là
    còn tour vượt cap, cron/apply-to-tours sẽ xử lý phần còn lại.

    LƯU Ý: caller phải invalidate_classification_cache() TRƯỚC khi gọi để
    resolver reload alias pairs mới từ DB (các _*_alias_pairs là lru_cache).
    """
    from sqlalchemy import func
    from sqlalchemy.orm import load_only

    from db_retry import run_with_retry
    from models import Tour

    alias_l = (alias or "").strip().lower()
    if not alias_l or kind not in ("company", "departure", "duration"):
        return {"applied": 0, "candidates": 0, "capped": False}

    if kind == "company":
        col = Tour.cong_ty
        cols = load_only(Tour.id, Tour.cong_ty)
    elif kind == "departure":
        col = Tour.diem_kh
        cols = load_only(Tour.id, Tour.diem_kh)
    else:  # duration
        col = Tour.thoi_gian
        cols = load_only(Tour.id, Tour.thoi_gian, Tour.so_ngay, Tour.manual_locked)

    def _do():
        db.rollback()  # session sạch cho mỗi attempt (pattern run_with_retry)
        rows = (
            _canonical_tour_query(db)
            .options(cols)
            .filter(func.lower(col).contains(alias_l, autoescape=True))
            .order_by(Tour.id)
            .limit(cap + 1)
            .all()
        )
        capped = len(rows) > cap
        rows = rows[:cap]
        n = 0
        for t in rows:
            if kind == "company":
                resolved = resolve_company_name(t.cong_ty)
                if resolved and resolved != (t.cong_ty or ""):
                    t.cong_ty = resolved[:256]
                    n += 1
            elif kind == "departure":
                resolved = resolve_departure_point(t.diem_kh)
                if resolved and resolved != (t.diem_kh or ""):
                    t.diem_kh = resolved[:256]
                    n += 1
            else:  # duration → so_ngay + chuẩn hóa text NĐ
                if getattr(t, "manual_locked", False):
                    continue  # admin khóa tay Thời gian → rule không ghi đè
                new_tg, new_sn = normalize_duration_text(t.thoi_gian, t.so_ngay)
                hit = False
                if new_sn is not None and (not t.so_ngay or float(t.so_ngay) != new_sn):
                    t.so_ngay = new_sn
                    hit = True
                if new_tg and new_tg != (t.thoi_gian or ""):
                    t.thoi_gian = new_tg[:64]
                    hit = True
                if hit:
                    n += 1
        db.commit()
        return n, len(rows), capped

    applied, scanned, capped = run_with_retry(_do, db=db, label=f"targeted-alias-{kind}")
    return {"applied": int(applied), "candidates": int(scanned), "capped": bool(capped)}


# ── Schedule (lich_kh) alias rules ───────────────────────────────────────────

# Mặc định seed khi bảng trống: các text lạ phổ biến → "" (bỏ qua khỏi
# thống kê tần suất đoàn). User có thể tự thêm canonical khác nếu muốn.
DEFAULT_SCHEDULE_ALIASES: list[tuple[str, list[str]]] = [
    ("", [
        "theo yêu cầu", "theo yeu cau",
        "liên hệ", "lien he",
        "hết hạn áp dụng", "het han ap dung",
        "ngưng khai thác", "ngung khai thac",
        "đang cập nhật", "dang cap nhat",
        "n/a", "—",
    ]),
]


def _schedule_pairs_from_defaults() -> tuple[tuple[str, str], ...]:
    pairs = []
    for canonical, aliases in DEFAULT_SCHEDULE_ALIASES:
        for a in aliases:
            pairs.append((0, len(a), a.lower().strip(), canonical))
    pairs.sort(key=lambda x: (x[0], -x[1]))
    return tuple((a, c) for _, _, a, c in pairs)


@lru_cache(maxsize=1)
def _schedule_alias_pairs() -> tuple[tuple[str, str], ...]:
    db = SessionLocal()
    try:
        rules = (
            db.query(ScheduleAliasRule)
            .filter(ScheduleAliasRule.active == True)
            .order_by(ScheduleAliasRule.sort_order, ScheduleAliasRule.id)
            .all()
        )
        if rules:
            pairs = [
                (r.sort_order, len(r.alias), r.alias.lower().strip(), (r.canonical_name or "").strip())
                for r in rules
                if r.alias.strip()
            ]
            pairs.sort(key=lambda x: (x[0], -x[1]))
            return tuple((a, c) for _, _, a, c in pairs)
    finally:
        db.close()
    return _schedule_pairs_from_defaults()


def _match_schedule_alias(text: str) -> str | None:
    """Trả về canonical (có thể là "") nếu khớp alias, None nếu không."""
    lower = (text or "").strip().lower()
    if not lower:
        return None
    for alias, canonical in _schedule_alias_pairs():
        if alias == lower:
            return canonical
    for alias, canonical in _schedule_alias_pairs():
        if _alias_matches_text(alias, lower):
            return canonical
    return None


def seed_schedule_aliases_from_defaults() -> int:
    from db_retry import run_with_retry

    def _do():
        db = SessionLocal()
        try:
            if db.query(ScheduleAliasRule).count() > 0:
                return 0
            order = 0
            for canonical, aliases in DEFAULT_SCHEDULE_ALIASES:
                for a in aliases:
                    db.add(ScheduleAliasRule(canonical_name=canonical, alias=a, sort_order=order))
                    order += 1
            db.commit()
            return order
        finally:
            db.close()

    n = run_with_retry(_do, label="seed-schedule-aliases")
    if n:
        invalidate_classification_cache()
    return n


def _stamp_tour_classified(t) -> None:
    """Đánh dấu tour đã qua lượt apply — dùng cho incremental lần sau."""
    from datetime import datetime

    now = datetime.utcnow()
    t.classified_at = now
    t.updated_at = now


def _apply_rule_result_to_tour(
    t,
    mk: str,
    rt: str,
    from_rule: bool,
    rule_id: int | None,
    *,
    update_derived: bool = True,
) -> tuple[int, int]:
    """Cập nhật thị trường/tuyến + metadata classify. Trả (market_n, route_n)."""
    # Admin đã khóa tay tour này → quy tắc KHÔNG được ghi đè thị trường/tuyến (đổi tên mới bỏ khóa, xử lý ở sync).
    if getattr(t, "manual_locked", False):
        return 0, 0
    market_n = route_n = 0
    changed = False
    if from_rule:
        if mk != (t.thi_truong or ""):
            t.thi_truong = mk[:128]
            market_n += 1
            changed = True
        if rt != (t.tuyen_tour or "").strip():
            t.tuyen_tour = rt[:256]
            route_n += 1
            changed = True
        if rule_id and t.classification_rule_id != rule_id:
            t.classification_rule_id = rule_id
            changed = True
    else:
        if (t.thi_truong or "").strip():
            t.thi_truong = ""
            market_n += 1
            changed = True
        if (t.tuyen_tour or "").strip():
            t.tuyen_tour = ""
            route_n += 1
            changed = True
        if t.classification_rule_id is not None:
            t.classification_rule_id = None
            changed = True
    if changed and update_derived:
        from tour_search import update_tour_derived_fields

        update_tour_derived_fields(t)
    return market_n, route_n


def _commit_tour_batch(db, batch, *, sync_search: bool = True) -> list[int]:
    from sqlalchemy.exc import IntegrityError
    from tour_search import sync_search_tsv_for_ids

    ids = [t.id for t in batch if t.id]
    try:
        db.commit()
    except IntegrityError as e:
        # FK race: user xóa rule X giữa lúc apply đang chạy với matcher cache cũ
        # (vẫn nghĩ rule X tồn tại). UPDATE thấy classification_rule_id=X → FK violation.
        # Rollback + invalidate cache → vòng apply tiếp theo sẽ rebuild matcher.
        # Log INFO không phải ERROR vì đây là race lành.
        db.rollback()
        if "tours_classification_rule_id_fkey" in str(e):
            logger.info(
                "FK race: rule bị xóa giữa lúc apply (%d tour trong batch bị bỏ). "
                "Invalidate matcher để vòng sau dùng cache mới.", len(batch),
            )
            invalidate_classification_cache()
            return []  # caller tiếp tục với batch sau
        raise
    if sync_search and ids:
        sync_search_tsv_for_ids(ids)
    return ids


def reclassify_tours_by_nguon(db, nguon: str, *, batch_size: int = 500) -> dict:
    """Chạy matcher cho mọi tour một nguồn (sau import Main không lấy B/C từ CSV)."""
    from data_sources import DB_CANONICAL_NGUON
    from models import Tour

    if nguon not in DB_CANONICAL_NGUON:
        return {"error": f"nguon không hợp lệ: {nguon}"}

    from db_retry import run_with_retry

    invalidate_classification_cache()
    matcher = get_route_rule_matcher()
    route_n = market_n = 0
    processed = 0
    last_id = 0
    while True:
        rows = (
            db.query(Tour)
            .filter(Tour.nguon == nguon, Tour.id > last_id)
            .order_by(Tour.id)
            .limit(batch_size)
            .all()
        )
        if not rows:
            break

        def _do(b=rows):
            db.rollback()  # re-apply lô sau rollback (idempotent: rule giống nhau → delta 0)
            m = r = 0
            for t in b:
                mk, rt, from_rule, rule_id = matcher.resolve(t.ten_tour or "", t.lich_trinh or "")
                md, rd = _apply_rule_result_to_tour(t, mk, rt, from_rule, rule_id)
                m += md
                r += rd
            db.commit()
            return m, r

        m_b, r_b = run_with_retry(_do, db=db, label="reclassify-batch")
        market_n += m_b
        route_n += r_b
        processed += len(rows)
        last_id = rows[-1].id
    try:
        from compare_cache import invalidate_compare_cache

        invalidate_compare_cache()
    except Exception:
        pass
    return {
        "nguon": nguon,
        "tours_scanned": processed,
        "route_updated": route_n,
        "market_updated": market_n,
    }


def _apply_all_rules_to_tours_locked(
    db,
    *,
    recompute_phan_khuc: bool = False,
    incremental: bool = True,
    start_after_id: int = 0,
    initial_processed: int = 0,
    total_override: int | None = None,
    progress_cb: callable | None = None,
) -> dict:
    """Một lượt quét tour — classification + alias công ty/KH/thời gian."""
    invalidate_classification_cache()
    matcher = get_route_rule_matcher()
    from link_utils import normalize_tour_link

    market_n = route_n = link_n = company_n = dep_n = dur_n = 0
    processed = max(0, int(initial_processed or 0))
    total = int(total_override) if total_override is not None else count_canonical_tours(db, incremental=incremental)
    defer_search = not incremental
    pending_search_ids: list[int] = []

    def _progress(n: int, total_n: int, msg: str, last_id: int | None = None) -> None:
        if not progress_cb:
            return
        try:
            progress_cb(n, total_n, msg, last_id)
        except TypeError:
            progress_cb(n, total_n, msg)

    affected_tour_ids: list[int] = []
    for batch in _iter_canonical_tour_batches(
        db,
        incremental=incremental,
        start_after_id=start_after_id,
    ):
        for i, t in enumerate(batch):
            derived_dirty = False
            mk, rt, from_rule, rule_id = matcher.resolve(t.ten_tour or "", t.lich_trinh or "")
            # RULE LÀ NGUỒN CHÂN LÝ cho Thị trường/Tuyến:
            #   - match  → set theo rule
            #   - KHÔNG match → để TRỐNG (tour vào panel "Chưa khớp" để admin tạo rule).
            # _apply_rule_result_to_tour TỰ bảo vệ manual_locked (admin set tay KHÔNG bị
            # đụng → return 0,0). Còn diem_kh/thoi_gian/cong_ty vẫn STICKY (các block
            # guarded bên dưới — chỉ ghi khi resolve ra giá trị mới, KHÔNG wipe).
            m_delta, r_delta = _apply_rule_result_to_tour(
                t,
                mk,
                rt,
                from_rule,
                rule_id,
                update_derived=False,
            )
            market_n += m_delta
            route_n += r_delta
            derived_dirty = bool(m_delta or r_delta)
            if m_delta or r_delta:
                affected_tour_ids.append(t.id)

            fixed_link = normalize_tour_link(t.link_url)
            if fixed_link != (t.link_url or ""):
                t.link_url = fixed_link
                link_n += 1

            resolved_co = resolve_company_name(t.cong_ty)
            if resolved_co and resolved_co != (t.cong_ty or ""):
                t.cong_ty = resolved_co[:256]
                company_n += 1
                derived_dirty = True

            resolved_dep = resolve_departure_point(t.diem_kh)
            if resolved_dep and resolved_dep != (t.diem_kh or ""):
                t.diem_kh = resolved_dep[:256]
                dep_n += 1
                derived_dirty = True

            # Chuẩn hóa Thời gian: khớp alias → ghi text dạng NĐ (7N6Đ) + so_ngay;
            # không khớp → giữ raw. Bỏ qua tour admin khóa tay.
            if not getattr(t, "manual_locked", False):
                new_tg, new_sn = normalize_duration_text(t.thoi_gian, t.so_ngay)
                if new_sn is not None and (not t.so_ngay or float(t.so_ngay) != new_sn):
                    t.so_ngay = new_sn
                    dur_n += 1
                if new_tg and new_tg != (t.thoi_gian or ""):
                    t.thoi_gian = new_tg[:64]

            if derived_dirty:
                from tour_search import update_tour_derived_fields

                update_tour_derived_fields(t)
            _stamp_tour_classified(t)

            if total and (i % 100 == 0 or i + 1 == len(batch)):
                _progress(
                    processed + i + 1,
                    total,
                    f"Đang quét {processed + i + 1}/{total} tour…",
                    t.id,
                )

        ids = _commit_tour_batch(db, batch, sync_search=not defer_search)
        if defer_search:
            pending_search_ids.extend(ids)
        processed += len(batch)
        _progress(processed, total, f"Đang quét {processed}/{total} tour…", batch[-1].id)

    if defer_search and pending_search_ids:
        try:
            from tour_search import sync_search_tsv_for_ids

            unique_ids = list({int(i) for i in pending_search_ids if i})
            for off in range(0, len(unique_ids), 500):
                sync_search_tsv_for_ids(unique_ids[off : off + 500])
                if total:
                    _progress(
                        processed,
                        total,
                        f"Đang lập chỉ mục tìm kiếm {min(off + 500, len(unique_ids))}/{len(unique_ids)}…",
                        unique_ids[min(off + 500, len(unique_ids)) - 1],
                    )
        except Exception as e:
            logger.warning("deferred search tsv sync failed: %s", e)

    result = {
        "market_updated": market_n,
        "route_updated": route_n,
        "links_repaired": link_n,
        "company_updated": company_n,
        "departure_updated": dep_n,
        "duration_updated": dur_n,
        "tours_scanned": processed,
        "tours_total": total,
        "incremental": incremental,
        "resumed_from_id": int(start_after_id or 0),
    }
    try:
        from segment_mv import refresh_segment_mv

        refresh_segment_mv()
    except Exception:
        pass
    # Invalidate route_avg cache vì TT/Tuyến vừa thay đổi → bucket key đổi.
    try:
        from pricing_segments import invalidate_route_avg_cache
        invalidate_route_avg_cache()
    except Exception:  # noqa: BLE001
        pass
    if recompute_phan_khuc:
        try:
            from pricing_segments import recompute_all_phan_khuc

            result["phan_khuc"] = recompute_all_phan_khuc(db)
        except Exception as e:
            logger.warning("recompute phan_khuc after rules apply failed: %s", e)
            result["phan_khuc"] = {"error": str(e)}
    else:
        # Mặc định: TÍNH LẠI phân khúc cho tour vừa đổi TT/Tuyến (affected_tour_ids)
        # + fill tour còn rỗng. Trước đây chỉ fill rỗng → tour có phân khúc cũ giữ
        # mismatch với TT mới sau apply rules.
        try:
            from pricing_segments import (
                recompute_missing_phan_khuc,
                recompute_phan_khuc_for_tour_ids,
            )
            if affected_tour_ids:
                result["phan_khuc_affected"] = recompute_phan_khuc_for_tour_ids(
                    db, affected_tour_ids
                )
            result["phan_khuc_filled"] = recompute_missing_phan_khuc(db)
            result["phan_khuc"] = {"affected_only": True, "count": len(affected_tour_ids)}
        except Exception as e:
            logger.warning("recompute phan_khuc affected after rules apply failed: %s", e)
            result["phan_khuc"] = {"error": str(e)}
    result["message"] = (
        f"Đã quét {processed}/{total} tour"
        f"{' (chỉ tour mới/cần cập nhật)' if incremental else ''} — "
        f"cập nhật thị trường {market_n}, tuyến {route_n}, "
        f"công ty {company_n}, điểm KH {dep_n}, thời gian {dur_n}"
    )
    try:
        from compare_cache import invalidate_compare_cache

        invalidate_compare_cache()
    except Exception:
        pass
    return result


def apply_all_rules_to_tours(
    db,
    *,
    recompute_phan_khuc: bool = False,
    incremental: bool = True,
    start_after_id: int = 0,
    initial_processed: int = 0,
    total_override: int | None = None,
    progress_cb: callable | None = None,
) -> dict:
    from db_job_lock import tours_write_lock
    from db_retry import run_with_retry

    def _do():
        db.rollback()  # mốc đọc mới; lỗi tạm thời trên commit lô → chạy lại cả apply (idempotent)
        with tours_write_lock(db, "apply_all_rules_to_tours") as locked:
            if not locked:
                raise RuntimeError("Đang có job khác ghi dữ liệu tour. Vui lòng thử lại sau.")
            return _apply_all_rules_to_tours_locked(
                db,
                recompute_phan_khuc=recompute_phan_khuc,
                incremental=incremental,
                start_after_id=start_after_id,
                initial_processed=initial_processed,
                total_override=total_override,
                progress_cb=progress_cb,
            )

    return run_with_retry(_do, db=db, label="apply-all-rules")


def _apply_classification_rules_to_tours_locked(
    db,
    *,
    keyword_filter: list[str] | None = None,
    route_state: str | None = None,
    clear_unmatched: bool = False,  # đổi từ True → False: tuyệt đối KHÔNG xóa giá trị unmatch.
    progress_cb: callable | None = None,
) -> dict:
    """
    Áp dụng rule tuyến lên tour.
    keyword_filter: chỉ quét tour có keyword trong tên/lịch trình (sau Gán).
    route_state: empty | filled | None (tất cả).
    """
    from link_utils import normalize_tour_link

    matcher = get_route_rule_matcher()
    market_n = route_n = link_n = 0
    processed = 0

    for batch in _iter_canonical_tour_batches(
        db, keyword_filter=keyword_filter, route_state=route_state
    ):
        for t in batch:
            mk, rt, from_rule, rule_id = matcher.resolve(t.ten_tour or "", t.lich_trinh or "")
            if from_rule:
                m_delta, r_delta = _apply_rule_result_to_tour(t, mk, rt, True, rule_id)
                market_n += m_delta
                route_n += r_delta
            elif clear_unmatched:
                m_delta, r_delta = _apply_rule_result_to_tour(t, "", "", False, None)
                market_n += m_delta
                route_n += r_delta
            fixed_link = normalize_tour_link(t.link_url)
            if fixed_link != (t.link_url or ""):
                t.link_url = fixed_link
                link_n += 1
            _stamp_tour_classified(t)
        _commit_tour_batch(db, batch)
        processed += len(batch)
        if progress_cb:
            progress_cb(processed, f"Phân loại {processed} tour…")

    try:
        from compare_cache import invalidate_compare_cache

        invalidate_compare_cache()
    except Exception:
        pass
    # Cache route_avg phụ thuộc TT/Tuyến → invalidate khi rule áp dụng.
    try:
        from pricing_segments import invalidate_route_avg_cache
        invalidate_route_avg_cache()
    except Exception:  # noqa: BLE001
        pass
    return {"market_updated": market_n, "route_updated": route_n, "links_repaired": link_n, "tours_scanned": processed}


def apply_classification_rules_to_tours(
    db,
    *,
    keyword_filter: list[str] | None = None,
    route_state: str | None = None,
    clear_unmatched: bool = False,  # PRESERVE RAW khi unmatch — KHÔNG xóa giá trị.
    progress_cb: callable | None = None,
) -> dict:
    from db_job_lock import tours_write_lock
    from db_retry import run_with_retry

    def _do():
        db.rollback()
        with tours_write_lock(db, "apply_classification_rules_to_tours") as locked:
            if not locked:
                raise RuntimeError("Đang có job khác ghi dữ liệu tour. Vui lòng thử lại sau.")
            return _apply_classification_rules_to_tours_locked(
                db,
                keyword_filter=keyword_filter,
                route_state=route_state,
                clear_unmatched=clear_unmatched,
                progress_cb=progress_cb,
            )

    return run_with_retry(_do, db=db, label="apply-classification-rules")


def apply_classification_for_keywords(db, keywords: list[str]) -> dict:
    """
    Sau Gán keyword → tuyến (2 bước):
    1) Tour trống tuyến + tên chứa keyword → gán mới.
    2) Tour đã có tuyến + tên chứa keyword → chạy lại matcher, điều chỉnh theo rule mới.
    """
    kws = [k.strip().lower() for k in keywords if k and str(k).strip()]
    if not kws:
        return apply_classification_rules_to_tours(db, clear_unmatched=False)

    phase_empty = apply_classification_rules_to_tours(
        db,
        keyword_filter=kws,
        route_state="empty",
        clear_unmatched=False,
    )
    phase_filled = apply_classification_rules_to_tours(
        db,
        keyword_filter=kws,
        route_state="filled",
        clear_unmatched=False,
    )
    empty_r = int(phase_empty.get("route_updated") or 0)
    adj_r = int(phase_filled.get("route_updated") or 0)
    empty_m = int(phase_empty.get("market_updated") or 0)
    adj_m = int(phase_filled.get("market_updated") or 0)
    scanned = int(phase_empty.get("tours_scanned") or 0) + int(phase_filled.get("tours_scanned") or 0)
    return {
        "phase_empty": phase_empty,
        "phase_filled": phase_filled,
        "tours_scanned": scanned,
        "route_updated": empty_r + adj_r,
        "market_updated": empty_m + adj_m,
        "empty_route_updated": empty_r,
        "filled_route_adjusted": adj_r,
        "message": (
            f"Tour trống: gán {empty_r} tuyến ({empty_m} TT); "
            f"tour đã có tuyến: điều chỉnh {adj_r} ({adj_m} TT); "
            f"quét {scanned} tour có keyword"
        ),
    }


def resolve_thi_truong(
    ten_tour: str,
    lich_trinh: str = "",
    *,
    market_pairs: tuple[tuple[str, str], ...] | None = None,
) -> str:
    combined = f"{ten_tour or ''} {lich_trinh or ''}".lower().strip()
    if not combined:
        return "Khác"
    pairs = market_pairs if market_pairs is not None else _load_market_keyword_pairs()
    for keyword, market in pairs:
        if keyword in combined:
            return market
    return "Khác"


@lru_cache(maxsize=1)
def _load_route_rules() -> tuple[tuple[int, str, str, tuple[str, ...]], ...]:
    """
    (thi_truong, tuyen_tour, keyword AND tuple) — cache process; gọi invalidate khi đổi rule.
    Ưu tiên: thị trường trên xuống (market order) → nhiều từ AND hơn trước → sort_order.
    """
    from classify_market_order import market_rank_map

    db = SessionLocal()
    try:
        rows = (
            db.query(RouteKeywordRule)
            .filter(RouteKeywordRule.active == True)
            .all()
        )
        ranks = market_rank_map(db, rows)

        def _row_key(r: RouteKeywordRule) -> tuple:
            kws = tuple(k.strip().lower() for k in r.keywords.split(",") if k.strip())
            mk = r.thi_truong.strip()
            # Hierarchy ưu tiên (thấp = chạy trước):
            #   1) Admin manual_locked tour → KHÔNG bị override (check ở _apply_rule_result_to_tour).
            #   2) System rule (base rules).
            #   3) Priority rule (priority=True) → apply BẤT KỂ thị trường có khớp hay không
            #      → KHÔNG sort theo market_rank, chỉ theo keyword count + sort_order.
            #   4) Other rules.
            # priority=True → bucket 0 (chạy trước), market_rank=0 (bỏ qua market).
            # priority=False → bucket 1, market_rank theo market order như cũ.
            if getattr(r, "priority", False):
                return (0, 0, -len(kws), r.sort_order, r.id)
            return (1, ranks.get(mk, 99999), -len(kws), r.sort_order, r.id)

        sorted_rows = sorted(rows, key=_row_key)
        out = []
        for r in sorted_rows:
            kws = tuple(k.strip().lower() for k in r.keywords.split(",") if k.strip())
            if kws:
                out.append((r.id, r.thi_truong.strip(), r.tuyen_tour.strip(), kws))
        return tuple(out)
    finally:
        db.close()


def _route_rules_from_db() -> tuple[tuple[int, str, str, tuple[str, ...]], ...]:
    return _load_route_rules()


def resolve_market_and_route(
    ten_tour: str,
    lich_trinh: str = "",
    *,
    route_rules: tuple[tuple[int, str, str, tuple[str, ...]], ...] | None = None,
    market_pairs: tuple[tuple[str, str], ...] | None = None,
) -> tuple[str, str, bool]:
    """
    (thị trường, tuyến, đã khớp rule tuyến).
    Thị trường chỉ lấy từ rule tuyến — không dùng keyword thị trường riêng.
    """
    _ = market_pairs  # legacy callers
    if route_rules is not None:
        from route_rule_matcher import RouteRuleMatcher

        m, r, ok, _ = RouteRuleMatcher(route_rules).resolve(ten_tour, lich_trinh)
        return m, r, ok
    m, r, ok, _ = get_route_rule_matcher().resolve(ten_tour, lich_trinh)
    return m, r, ok


def classify_route_fields(ten_tour: str, lich_trinh: str = "") -> tuple[str, str]:
    """Thị trường + tuyến từ rule; không khớp → chuỗi rỗng."""
    mk, rt, ok = resolve_market_and_route(ten_tour or "", lich_trinh or "")
    if ok:
        return mk, rt
    return "", ""


def resolve_tuyen_tour(thi_truong: str, ten_tour: str, lich_trinh: str = "") -> str:
    """Trả về tuyến; tham số thi_truong giữ tương thích API cũ (không còn lọc theo market)."""
    _mk, route, _matched = resolve_market_and_route(ten_tour, lich_trinh)
    return route


def seed_route_rules_from_bundle(db=None, *, force: bool = False) -> int:
    """Seed quy tắc tuyến từ backend/data/route_rules.json → Supabase (không đọc Sheet)."""
    import json
    from pathlib import Path

    from db_retry import run_with_retry

    path = Path(__file__).parent / "data" / "route_rules.json"
    if not path.is_file():
        logger.warning("route_rules.json not found — skip route seed")
        return 0

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        def _do():
            db.rollback()  # delete+add+commit idempotent (count-check / force re-delete) → retry an toàn
            if not force and db.query(RouteKeywordRule).count() > 0:
                return 0
            rows = json.loads(path.read_text(encoding="utf-8"))
            if force:
                db.query(RouteKeywordRule).delete()
            count = 0
            for row in rows:
                kws = (row.get("keywords") or "").strip()
                if not kws:
                    continue
                db.add(
                    RouteKeywordRule(
                        thi_truong=row["thi_truong"],
                        tuyen_tour=row.get("tuyen_tour") or row["thi_truong"],
                        keywords=kws,
                        sort_order=int(row.get("sort_order", count)),
                    )
                )
                count += 1
            db.commit()
            invalidate_classification_cache()
            try:
                from route_rule_tokens import rebuild_route_rule_tokens

                rebuild_route_rule_tokens(db)
            except Exception:
                pass
            return count

        count = run_with_retry(_do, db=db, label="seed-route-rules")
        logger.info("Seeded %s route rules from bundle", count)
        return count
    finally:
        if own_session:
            db.close()


def seed_market_rules_from_hardcode() -> int:
    """Import MARKET_KEYWORDS vào DB (bỏ qua nếu đã có)."""
    from db_retry import run_with_retry

    def _do():
        db = SessionLocal()
        try:
            if db.query(MarketKeywordRule).count() > 0:
                return 0
            count = 0
            order = 0
            for market, keywords in _HARDCODED_MARKET.items():
                for kw in keywords:
                    db.add(MarketKeywordRule(market=market, keyword=kw, sort_order=order))
                    count += 1
                    order += 1
            db.commit()
            return count
        finally:
            db.close()

    n = run_with_retry(_do, label="seed-market-rules")
    if n:
        invalidate_classification_cache()
    return n
