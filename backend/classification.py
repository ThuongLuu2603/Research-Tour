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


@lru_cache(maxsize=1)
def _market_keyword_pairs() -> tuple[tuple[str, str], ...]:
    pairs = _sorted_market_pairs_from_db()
    if not pairs:
        pairs = _sorted_market_pairs_fallback()
    return tuple(pairs)


def invalidate_classification_cache() -> None:
    _market_keyword_pairs.cache_clear()
    _route_rules_from_db.cache_clear()
    _company_alias_pairs.cache_clear()
    _departure_alias_pairs.cache_clear()
    _duration_alias_pairs.cache_clear()


DEFAULT_DURATION_ALIASES: list[tuple[float, list[str]]] = [
    (3.0, ["3n2d", "3n/2d", "3 ngày 2 đêm", "3 ngày 2 dem", "3n 2d"]),
    (4.0, ["4n3d", "4n/3d", "4 ngày 3 đêm", "4 ngày 3 dem", "4n 3d"]),
    (5.0, ["5n4d", "5n/4d", "5 ngày 4 đêm", "5 ngày 4 dem", "5n 4d", "5n4đ"]),
    (6.0, ["6n5d", "6n/5d", "6 ngày 5 đêm", "6 ngày 5 dem"]),
    (7.0, ["7n6d", "7n/6d", "7 ngày 6 đêm", "7 ngày 6 dem"]),
    (8.0, ["8n7d", "8n/7d", "8 ngày 7 đêm"]),
    (9.0, ["9n8d", "9 ngày 8 đêm"]),
    (10.0, ["10n9d", "10 ngày 9 đêm"]),
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
        "note": "Khi db_rules > 0, runtime chỉ đọc Quy tắc vận hành. Sau khi sửa rule, bấm «Áp dụng → tour».",
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


def apply_duration_aliases_to_tours(db) -> int:
    from models import Tour
    count = 0
    for t in db.query(Tour).all():
        days, matched = resolve_duration_days(t.thoi_gian, t.so_ngay)
        if days is None:
            continue
        changed = False
        if matched and (not t.so_ngay or float(t.so_ngay) != days):
            t.so_ngay = days
            changed = True
        if changed:
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
    """Trả về (số ngày, đã khớp alias/so_ngay chuẩn)."""
    if so_ngay and 0 < so_ngay <= 45:
        return round(float(so_ngay), 1), True
    text = re.sub(r"\s+", " ", (thoi_gian or "").strip().lower())
    if text:
        for alias, days in _duration_alias_pairs():
            if alias == text or alias in text:
                return days, True
    if not thoi_gian:
        return None, False
    s = thoi_gian.strip().lower()
    m = re.search(r"(\d+)\s*n\s*(\d+)\s*[dđ]", s)
    if m:
        return float(m.group(1)), False
    m = re.search(r"(\d+)\s*ngày", s)
    if m:
        d = float(m.group(1))
        return (d, False) if 0 < d <= 45 else (None, False)
    m = re.search(r"(\d+)\s*n\b", s)
    if m:
        d = float(m.group(1))
        return (d, False) if 0 < d <= 45 else (None, False)
    return None, False


def collect_unmatched_values(tours: list, *, vtr_only: bool = True) -> dict:
    """Giá trị chưa khớp alias — Công ty, Điểm KH, Thời gian."""
    from tour_sources import is_vietravel_tab

    cong_ty: dict[str, int] = {}
    diem_kh: dict[str, int] = {}
    thoi_gian: dict[str, int] = {}

    for t in tours:
        if vtr_only and not is_vietravel_tab(t):
            continue
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

    return {
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
    from models import Tour
    count = 0
    for t in db.query(Tour).all():
        resolved = resolve_company_name(t.cong_ty)
        if resolved and resolved != t.cong_ty:
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
    from models import Tour
    count = 0
    for t in db.query(Tour).all():
        resolved = resolve_departure_point(t.diem_kh)
        if resolved and resolved != t.diem_kh:
            t.diem_kh = resolved[:256]
            count += 1
    db.commit()
    return count


def apply_classification_rules_to_tours(db) -> dict:
    """Áp dụng lại rules Thị trường + Tuyến tour cho toàn bộ tour."""
    from link_utils import normalize_tour_link
    from models import Tour

    market_n = route_n = link_n = 0
    for t in db.query(Tour).all():
        mk = resolve_thi_truong(t.ten_tour or "", t.lich_trinh or "")
        rt = resolve_tuyen_tour(mk, t.ten_tour or "", t.lich_trinh or "")
        if mk and mk != (t.thi_truong or ""):
            t.thi_truong = mk[:128]
            market_n += 1
        current_route = (t.tuyen_tour or "").strip()
        if rt and rt != current_route:
            # Không thay tuyến cụ thể (vd. Bờ Đông) bằng nhãn thị trường chung (Châu Mỹ)
            if rt == mk and current_route and current_route.casefold() not in {mk.casefold(), "khác", "khac"}:
                pass
            else:
                t.tuyen_tour = rt[:256]
                route_n += 1
        fixed_link = normalize_tour_link(t.link_url)
        if fixed_link != (t.link_url or ""):
            t.link_url = fixed_link
            link_n += 1
    db.commit()
    try:
        from compare_cache import invalidate_compare_cache
        invalidate_compare_cache()
    except Exception:
        pass
    return {"market_updated": market_n, "route_updated": route_n, "links_repaired": link_n}


def resolve_thi_truong(ten_tour: str, lich_trinh: str = "") -> str:
    combined = f"{ten_tour or ''} {lich_trinh or ''}".lower().strip()
    if not combined:
        return "Khác"
    for keyword, market in _market_keyword_pairs():
        if keyword in combined:
            return market
    return "Khác"


@lru_cache(maxsize=1)
def _route_rules_from_db() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """(thi_truong, tuyen_tour, keyword_tuple) ordered by sort_order."""
    db = SessionLocal()
    try:
        rules = (
            db.query(RouteKeywordRule)
            .filter(RouteKeywordRule.active == True)
            .order_by(RouteKeywordRule.sort_order, RouteKeywordRule.id)
            .all()
        )
        out = []
        for r in rules:
            kws = tuple(k.strip().lower() for k in r.keywords.split(",") if k.strip())
            if kws:
                out.append((r.thi_truong.strip(), r.tuyen_tour.strip(), kws))
        return tuple(out)
    finally:
        db.close()


def _route_rules_from_sheet() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    try:
        from scrapers.route_rules import load_route_rules
        raw = load_route_rules()
        out = []
        for market, rule_list in raw.items():
            for rule in rule_list:
                kws = tuple(kw.strip().lower() for kw in rule.get("keywords", []) if kw.strip())
                if kws:
                    out.append((market, rule.get("route", market), kws))
        return tuple(out)
    except Exception as e:
        logger.warning("Could not load route rules from sheet: %s", e)
        return ()


def resolve_tuyen_tour(thi_truong: str, ten_tour: str, lich_trinh: str = "") -> str:
    market = (thi_truong or "").strip()
    combined = f"{ten_tour or ''} {lich_trinh or ''}".lower()

    rules = _route_rules_from_db()
    if not rules:
        rules = _route_rules_from_sheet()

    for mkt, route, kws in rules:
        if mkt == market and all(kw in combined for kw in kws):
            return route
    return market or "Khác"


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
