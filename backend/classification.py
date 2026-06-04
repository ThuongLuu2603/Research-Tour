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
from models import MarketKeywordRule, RouteKeywordRule, CompanyAliasRule, DepartureAliasRule

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


def _market_keyword_pairs() -> tuple[tuple[str, str], ...]:
    return _load_market_keyword_pairs()


def invalidate_classification_cache() -> None:
    _company_alias_pairs.cache_clear()
    _departure_alias_pairs.cache_clear()
    _duration_alias_pairs.cache_clear()
    _load_route_rules.cache_clear()
    global _route_matcher
    _route_matcher = None
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
    db = SessionLocal()
    try:
        if db.query(DurationAliasRule).count() > 0:
            return 0
        order = 0
        for days, aliases in DEFAULT_DURATION_ALIASES:
            for a in aliases:
                db.add(DurationAliasRule(canonical_days=days, alias=a, sort_order=order))
                order += 1
        db.commit()
        invalidate_classification_cache()
        return order
    finally:
        db.close()


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
    batch_size: int = 1000,
    *,
    keyword_filter: list[str] | None = None,
    route_state: str | None = None,
    incremental: bool = False,
):
    """Phân trang theo id — chỉ cột cần cho apply rule."""
    from sqlalchemy.orm import load_only

    from models import Tour

    cols = load_only(
        Tour.id,
        Tour.ten_tour,
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
    )
    last_id = 0
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
    count = 0
    for batch in _iter_canonical_tour_batches(db):
        for t in batch:
            days, matched = resolve_duration_days(t.thoi_gian, t.so_ngay)
            if days is None:
                continue
            if matched and (not t.so_ngay or float(t.so_ngay) != days):
                t.so_ngay = days
                count += 1
        db.commit()
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
        db.commit()
        from tour_search import sync_search_tsv_for_ids

        sync_search_tsv_for_ids(healed_ids)

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
    thi_truong: dict[str, dict] = {}
    tuyen_tour: dict[str, dict] = {}
    classify_gaps: dict[str, dict] = {}

    matcher = get_route_rule_matcher()
    for t in tours:
        if vtr_only and not is_vietravel_tab(t):
            continue
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

        raw_co = (t.cong_ty or "").strip()
        if raw_co and not is_company_alias_matched(raw_co):
            cong_ty[raw_co] = cong_ty.get(raw_co, 0) + 1
        raw_dep = (t.diem_kh or "").strip()
        if raw_dep and not is_departure_alias_matched(raw_dep):
            diem_kh[raw_dep] = diem_kh.get(raw_dep, 0) + 1
        raw_tg = (t.thoi_gian or "").strip()
        days, matched = resolve_duration_days(raw_tg, t.so_ngay)
        if days is None or (raw_tg and not matched):
            key = raw_tg or (f"so_ngay={t.so_ngay}" if t.so_ngay else "—")
            thoi_gian[key] = thoi_gian.get(key, 0) + 1

    def _rows(d: dict[str, int]) -> list[dict]:
        return sorted([{"value": k, "count": v} for k, v in d.items()], key=lambda x: -x["count"])[:40]

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
    )[:40]
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
    )[:40]

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
    )[:50]

    return {
        "thi_truong": market_rows,
        "tuyen_tour": route_rows,
        "classify": classify_rows,
        "cong_ty": _rows(cong_ty),
        "diem_kh": _rows(diem_kh),
        "thoi_gian": _rows(thoi_gian),
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
        invalidate_classification_cache()
        return order
    finally:
        db.close()


def apply_company_aliases_to_tours(db) -> int:
    count = 0
    for batch in _iter_canonical_tour_batches(db):
        for t in batch:
            resolved = resolve_company_name(t.cong_ty)
            if resolved and resolved != (t.cong_ty or ""):
                t.cong_ty = resolved[:256]
                count += 1
        db.commit()
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
    """Chuẩn hóa điểm khởi hành từ alias → tên chính thức."""
    s = (raw or "").strip()
    if not s:
        return ""
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
        invalidate_classification_cache()
        return order
    finally:
        db.close()


def apply_departure_aliases_to_tours(db) -> int:
    count = 0
    for batch in _iter_canonical_tour_batches(db):
        for t in batch:
            resolved = resolve_departure_point(t.diem_kh)
            if resolved and resolved != (t.diem_kh or ""):
                t.diem_kh = resolved[:256]
                count += 1
        db.commit()
    return count


def _stamp_tour_classified(t) -> None:
    """Đánh dấu tour đã qua lượt apply — dùng cho incremental lần sau."""
    from datetime import datetime

    now = datetime.utcnow()
    t.classified_at = now
    t.updated_at = now


def _apply_rule_result_to_tour(t, mk: str, rt: str, from_rule: bool, rule_id: int | None) -> tuple[int, int]:
    """Cập nhật thị trường/tuyến + metadata classify. Trả (market_n, route_n)."""
    from datetime import datetime

    from tour_search import update_tour_derived_fields

    market_n = route_n = 0
    if from_rule:
        if mk != (t.thi_truong or ""):
            t.thi_truong = mk[:128]
            market_n += 1
        if rt != (t.tuyen_tour or "").strip():
            t.tuyen_tour = rt[:256]
            route_n += 1
        if rule_id and t.classification_rule_id != rule_id:
            t.classification_rule_id = rule_id
    else:
        if (t.thi_truong or "").strip():
            t.thi_truong = ""
            market_n += 1
        if (t.tuyen_tour or "").strip():
            t.tuyen_tour = ""
            route_n += 1
        if t.classification_rule_id is not None:
            t.classification_rule_id = None
    update_tour_derived_fields(t)
    return market_n, route_n


def _commit_tour_batch(db, batch) -> None:
    from tour_search import sync_search_tsv_for_ids

    ids = [t.id for t in batch if t.id]
    db.commit()
    if ids:
        sync_search_tsv_for_ids(ids)


def apply_all_rules_to_tours(
    db,
    *,
    recompute_phan_khuc: bool = False,
    incremental: bool = True,
    progress_cb: callable | None = None,
) -> dict:
    """Một lượt quét tour — classification + alias công ty/KH/thời gian."""
    invalidate_classification_cache()
    matcher = get_route_rule_matcher()
    from link_utils import normalize_tour_link

    market_n = route_n = link_n = company_n = dep_n = dur_n = 0
    processed = 0
    total = count_canonical_tours(db, incremental=incremental)

    for batch in _iter_canonical_tour_batches(db, incremental=incremental):
        for i, t in enumerate(batch):
            mk, rt, from_rule, rule_id = matcher.resolve(t.ten_tour or "", t.lich_trinh or "")
            m_delta, r_delta = _apply_rule_result_to_tour(t, mk, rt, from_rule, rule_id)
            market_n += m_delta
            route_n += r_delta

            fixed_link = normalize_tour_link(t.link_url)
            if fixed_link != (t.link_url or ""):
                t.link_url = fixed_link
                link_n += 1

            resolved_co = resolve_company_name(t.cong_ty)
            if resolved_co and resolved_co != (t.cong_ty or ""):
                t.cong_ty = resolved_co[:256]
                company_n += 1

            resolved_dep = resolve_departure_point(t.diem_kh)
            if resolved_dep and resolved_dep != (t.diem_kh or ""):
                t.diem_kh = resolved_dep[:256]
                dep_n += 1

            days, matched = resolve_duration_days(t.thoi_gian, t.so_ngay)
            if days is not None and matched and (not t.so_ngay or float(t.so_ngay) != days):
                t.so_ngay = days
                dur_n += 1

            _stamp_tour_classified(t)

            if progress_cb and total and (i % 200 == 0 or i + 1 == len(batch)):
                progress_cb(
                    processed + i + 1,
                    total,
                    f"Đang quét {processed + i + 1}/{total} tour…",
                )

        _commit_tour_batch(db, batch)
        processed += len(batch)
        if progress_cb:
            progress_cb(processed, total, f"Đang quét {processed}/{total} tour…")

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
    }
    try:
        from segment_mv import refresh_segment_mv

        refresh_segment_mv()
    except Exception:
        pass
    if recompute_phan_khuc:
        try:
            from pricing_segments import recompute_all_phan_khuc

            result["phan_khuc"] = recompute_all_phan_khuc(db)
        except Exception as e:
            logger.warning("recompute phan_khuc after rules apply failed: %s", e)
            result["phan_khuc"] = {"error": str(e)}
    else:
        result["phan_khuc"] = {"skipped": True}
        try:
            from pricing_segments import recompute_missing_phan_khuc

            result["phan_khuc_filled"] = recompute_missing_phan_khuc(db)
        except Exception as e:
            logger.warning("recompute missing phan_khuc failed: %s", e)
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


def apply_classification_rules_to_tours(
    db,
    *,
    keyword_filter: list[str] | None = None,
    route_state: str | None = None,
    clear_unmatched: bool = True,
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
    return {"market_updated": market_n, "route_updated": route_n, "links_repaired": link_n, "tours_scanned": processed}


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
            return (ranks.get(mk, 99999), -len(kws), r.sort_order, r.id)

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

    path = Path(__file__).parent / "data" / "route_rules.json"
    if not path.is_file():
        logger.warning("route_rules.json not found — skip route seed")
        return 0

    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
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
        logger.info("Seeded %s route rules from bundle", count)
        return count
    finally:
        if own_session:
            db.close()


def seed_market_rules_from_hardcode() -> int:
    """Import MARKET_KEYWORDS vào DB (bỏ qua nếu đã có)."""
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
        invalidate_classification_cache()
        return count
    finally:
        db.close()
