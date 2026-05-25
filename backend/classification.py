"""Phân loại thị trường / tuyến tour — đọc từ DB, fallback hardcode/sheet."""
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


DEFAULT_COMPANY_ALIASES: list[tuple[str, list[str]]] = [
    ("Vietravel", ["vietravel", "viet travel", "travel.com.vn", "cong ty co phan vietravel"]),
    ("Saigontourist", ["saigontourist", "sai gon tourist", "sgt"]),
    ("Fiditour", ["fiditour", "fidi tour"]),
    ("Tugo", ["tugo", "tu go"]),
    ("Hanoitourist", ["hanoitourist", "ha noi tourist"]),
    ("Ben Thanh Tourist", ["ben thanh tourist", "benthancorp", "ben thanh"]),
    ("Transviet", ["transviet", "trans viet"]),
    ("Luxury Travel", ["luxury travel", "luxurytravel"]),
]


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
        pairs = [(r.alias.lower().strip(), r.canonical_name.strip()) for r in rules if r.alias.strip()]
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        if pairs:
            return tuple(pairs)
    finally:
        db.close()
    pairs = []
    for canonical, aliases in DEFAULT_COMPANY_ALIASES:
        for a in aliases:
            pairs.append((a.lower().strip(), canonical))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return tuple(pairs)


def resolve_company_name(raw_name: str) -> str:
    """Chuẩn hóa tên công ty từ alias → tên chính thức."""
    s = (raw_name or "").strip()
    if not s:
        return ""
    lower = s.lower()
    for alias, canonical in _company_alias_pairs():
        if alias == lower or alias in lower:
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
        pairs = [(r.alias.lower().strip(), r.canonical_name.strip()) for r in rules if r.alias.strip()]
        pairs.sort(key=lambda x: len(x[0]), reverse=True)
        if pairs:
            return tuple(pairs)
    finally:
        db.close()
    pairs = []
    for canonical, aliases in DEFAULT_DEPARTURE_ALIASES:
        for a in aliases:
            pairs.append((a.lower().strip(), canonical))
    pairs.sort(key=lambda x: len(x[0]), reverse=True)
    return tuple(pairs)


def _match_departure_alias(text: str) -> str | None:
    lower = (text or "").strip().lower()
    if not lower:
        return None
    for alias, canonical in _departure_alias_pairs():
        if alias == lower or alias in lower:
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
