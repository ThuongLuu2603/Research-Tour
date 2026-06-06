"""So sánh Vietravel vs thị trường & đối thủ — giá/ngày + tần suất KH theo segment."""
from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from config import settings
from departure_parser import (
    parse_departure_frequency,
    parse_departure_frequency_in_period,
    parse_departure_dates,
    schedules_overlap_vtr_period,
    vtr_period_label,
)
from models import Tour
from stats_utils import robust_weighted_avg, weighted_avg, weighted_median

COMPANY = settings.company_name
# Main = catalog thị trường chuẩn; Vietravel tab riêng; FindTourGo không vào compare (xem tour_sources.py)
NGUON_PRIORITY = {"Main": 3, "Manual": 2, "Vietravel": 2, "FindTourGo": 0}

# Giá/ngày bất thường (parse Sheet lỗi) làm vỡ biểu đồ & chênh %
MAX_TOUR_PRICE_VND = 300_000_000
MAX_PRICE_PER_DAY_VND = 50_000_000
MIN_TOUR_DAYS = 0.5
MAX_TOUR_DAYS = 45

DEPART_ALIASES: list[tuple[str, str]] = []  # legacy; dùng classification.resolve_departure_point


def normalize_departure(diem_kh: str) -> str:
    from classification import resolve_departure_point
    resolved = resolve_departure_point(diem_kh or "")
    return resolved or "Khác"


def normalize_route(tuyen_tour: str) -> str:
    return re.sub(r"\s+", " ", (tuyen_tour or "").strip())[:256]


def route_for_segment(t: Tour) -> str:
    """Tuyến dùng để gom nhóm — ưu tiên cột Tuyến tour, không ghi đè bằng tên thị trường."""
    from classification import resolve_market_and_route

    market, resolved_route, from_route_rule = resolve_market_and_route(t.ten_tour or "", t.lich_trinh or "")
    market = market or (t.thi_truong or "").strip() or "Khác"
    explicit = normalize_route(t.tuyen_tour)
    generic = {market.casefold(), "khác", "khac", ""}
    if explicit and explicit.casefold() not in generic:
        return explicit
    resolved = normalize_route(resolved_route)
    if from_route_rule and resolved:
        return resolved
    if resolved and resolved.casefold() not in generic:
        return resolved
    return explicit or resolved or market


def is_vietravel(cong_ty: str) -> bool:
    from classification import resolve_company_name
    resolved = resolve_company_name(cong_ty or "")
    return settings.company_name.lower() in resolved.lower()


def parse_duration_days(thoi_gian: str, so_ngay: float | None) -> float | None:
    from classification import resolve_duration_days
    days, _matched = resolve_duration_days(thoi_gian, so_ngay)
    return days


def _safe_num(v: float | int | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return float(v)


def _sanitize_tour_price(gia: float | None) -> float | None:
    g = _safe_num(gia)
    if g is None or g <= 0 or g > MAX_TOUR_PRICE_VND:
        return None
    return g


def _sanitize_tour_days(days: float | None) -> float | None:
    d = _safe_num(days)
    if d is None or d < MIN_TOUR_DAYS or d > MAX_TOUR_DAYS:
        return None
    return d


def make_segment_key(thi_truong: str, route: str, depart: str) -> str:
    """Nhóm so sánh = Thị trường + Tuyến + Điểm KH (không tách theo số ngày)."""
    return f"{thi_truong}|{route}|{depart}"


def parse_segment_key(key: str) -> tuple[str, str, str] | None:
    """Parse segment key → (thi_truong, route, depart). Hỗ trợ key cũ có |{days}d."""
    if not key or "|" not in key:
        return None
    parts = key.rsplit("|", 2)
    if len(parts) == 3 and not parts[2].endswith("d"):
        return parts[0], parts[1], parts[2]
    legacy = key.rsplit("|", 3)
    if len(legacy) == 4 and legacy[3].endswith("d"):
        return legacy[0], legacy[1], legacy[2]
    return None


def segment_key(tour: Tour) -> str | None:
    route = route_for_segment(tour)
    depart = normalize_departure(tour.diem_kh)
    market = (tour.thi_truong or "").strip() or "Khác"
    if not route or not tour.gia or tour.gia <= 0:
        return None
    days = parse_duration_days(tour.thoi_gian, tour.so_ngay)
    if not days:
        return None
    return make_segment_key(market, route, depart)


def _dedup_key(t: Tour) -> str:
    """Chỉ gộp trùng mã/link thật — không gộp mọi tour cùng CTY chỉ vì link placeholder."""
    from link_utils import normalize_tour_link

    ma = (t.ma_tour or "").strip().lower()
    link = normalize_tour_link(t.link_url)
    company = (t.cong_ty or "").strip().lower()
    if ma:
        return f"{company}|ma:{ma}"
    if link:
        return f"{company}|{link.lower()}"
    ten = re.sub(r"\s+", " ", (t.ten_tour or "").strip().lower())[:160]
    if ten:
        return f"{company}|name:{ten}"
    return f"{company}|id:{t.id}"


def _tour_priority(t: Tour) -> tuple:
    src = NGUON_PRIORITY.get(t.nguon or "", 0)
    updated = t.updated_at.timestamp() if t.updated_at else 0
    return (src, updated)


def _is_specific_route(tuyen_tour: str, thi_truong: str) -> bool:
    route = (tuyen_tour or "").strip()
    market = (thi_truong or "").strip()
    generic = {market.casefold(), "khác", "khac", ""}
    return bool(route and route.casefold() not in generic)


def _prefer_route_label(keep: Tour, drop: Tour) -> None:
    """Giữ nhãn tuyến cụ thể (vd. Bờ Đông) từ Main/Manual khi dedup với FindTourGo."""
    if not _is_specific_route(drop.tuyen_tour, drop.thi_truong or keep.thi_truong):
        return
    if not _is_specific_route(keep.tuyen_tour, keep.thi_truong or drop.thi_truong):
        keep.tuyen_tour = (drop.tuyen_tour or "")[:256]
        return
    curated = {"Manual", "Main"}
    if drop.nguon in curated and keep.nguon not in curated:
        keep.tuyen_tour = (drop.tuyen_tour or "")[:256]


def deduplicate_tours(tours: list[Tour]) -> list[Tour]:
    best: dict[str, Tour] = {}
    for t in tours:
        k = _dedup_key(t)
        if k not in best or _tour_priority(t) > _tour_priority(best[k]):
            if k in best:
                _prefer_route_label(t, best[k])
            best[k] = t
        else:
            _prefer_route_label(best[k], t)
    return list(best.values())


@dataclass
class TourEntry:
    tour_id: int
    cong_ty: str
    ten_tour: str
    gia: float
    gia_raw: str
    so_ngay: float
    price_day: float
    freq_score: float
    freq_label: str
    lich_kh: str
    lich_trinh: str
    link_url: str
    thoi_gian: str
    is_vietravel: bool
    phan_khuc: str = ""   # phân khúc giá tự tính (Standard/Premium/Luxury) — lọc giá phía thị trường
    dong_tour: str = ""   # Dòng tour VTR (Tiết kiệm/Giá Tốt…) — lọc giá phía Vietravel


# ── Quy tắc lọc khi SO SÁNH GIÁ (tần suất vẫn dùng toàn bộ tour) ──────────────
# Phía Vietravel: chỉ tính tour thuộc các Dòng tour này.
VTR_PRICE_TIERS = {"tiết kiệm", "giá tốt"}
# Phía thị trường (giá so sánh): chỉ tính tour có phân khúc giá này.
MARKET_PRICE_PHAN_KHUC = {"premium"}


def _norm_tier(s: str) -> str:
    return (s or "").strip().lower()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 0)


def _departure_weight(entry: TourEntry, vtr_dates: list, *, in_vtr_period: bool) -> float:
    """Trọng số = số đoàn KH (ưu tiên đếm ngày cố định trong giai đoạn VTR)."""
    if in_vtr_period and vtr_dates:
        info = parse_departure_frequency_in_period(entry.lich_kh, vtr_dates)
        explicit = info.get("explicit_dates") or 0
        if explicit > 0:
            return float(explicit)
        est = info.get("monthly_estimate") or 0
        if est > 0:
            return float(est)
    info = parse_departure_frequency(entry.lich_kh)
    explicit = info.get("explicit_dates") or 0
    if explicit > 0:
        return float(explicit)
    return max(float(info.get("monthly_estimate") or entry.freq_score or 1.0), 1.0)


def _departure_weights(entries: list[TourEntry], vtr_dates: list, *, in_vtr_period: bool) -> list[float]:
    return [_departure_weight(e, vtr_dates, in_vtr_period=in_vtr_period) for e in entries]


def _route_avg_days(entries: list[TourEntry], weights: list[float]) -> float | None:
    """Số ngày TB tuyến = Σ(đoàn × ngày) / Σ(đoàn)."""
    total_w = sum(weights)
    if total_w <= 0:
        return None
    return round(sum(e.so_ngay * w for e, w in zip(entries, weights)) / total_w, 1)


def _route_avg_price_per_day(entries: list[TourEntry], weights: list[float]) -> float | None:
    """Giá TB/ngày = Σ(giá tour × đoàn) / Σ(đoàn × ngày)."""
    if not entries or not weights:
        return None
    num = sum(e.gia * w for e, w in zip(entries, weights))
    den = sum(e.so_ngay * w for e, w in zip(entries, weights))
    if den <= 0:
        return None
    val = round(num / den, 0)
    if val <= 0 or val > MAX_PRICE_PER_DAY_VND:
        return None
    return val


def _route_total_price(avg_day: float | None, avg_days: float | None) -> float | None:
    if avg_day is None or avg_days is None:
        return None
    total = round(avg_day * avg_days, 0)
    if total <= 0 or total > MAX_TOUR_PRICE_VND:
        return None
    return total


def _smart_price_avg(entries: list[TourEntry], *, vtr: bool) -> float | None:
    """Giá TB có trọng số; thị trường dùng robust khi biên độ giá lớn."""
    pairs = [(e.gia, e.freq_score) for e in entries]
    if not pairs:
        return None
    if vtr or len(pairs) < 4:
        return weighted_avg(pairs)
    return robust_weighted_avg(pairs)


def _smart_day_avg(entries: list[TourEntry], *, vtr: bool) -> float | None:
    pairs = [(e.price_day, e.freq_score) for e in entries]
    if not pairs:
        return None
    if vtr or len(pairs) < 4:
        return weighted_avg(pairs)
    return robust_weighted_avg(pairs)


@dataclass
class CompanySegmentStats:
    cong_ty: str
    tour_count: int = 0
    freq_monthly: float = 0.0
    avg_departures_per_month: float = 0.0
    avg_price_day: float | None = None
    median_price_day: float | None = None
    min_price_day: float | None = None
    max_price_day: float | None = None

    def to_dict(self) -> dict:
        return {
            "cong_ty": self.cong_ty,
            "tour_count": self.tour_count,
            "freq_monthly": round(self.freq_monthly, 1),
            "avg_departures_per_month": round(self.avg_departures_per_month, 1),
            "avg_price_day": self.avg_price_day,
            "median_price_day": self.median_price_day,
            "min_price_day": self.min_price_day,
            "max_price_day": self.max_price_day,
        }


@dataclass
class SegmentStats:
    key: str
    thi_truong: str
    tuyen_tour: str
    diem_kh: str
    so_ngay: float
    entries: list[TourEntry] = field(default_factory=list)

    @property
    def vtr_entries(self) -> list[TourEntry]:
        return [e for e in self.entries if e.is_vietravel]

    @property
    def market_entries(self) -> list[TourEntry]:
        return [e for e in self.entries if not e.is_vietravel]

    def _vtr_period_dates(self) -> list:
        dates = []
        for e in self.vtr_entries:
            dates.extend(parse_departure_dates(e.lich_kh))
        return dates

    @property
    def vtr_comparison_period(self) -> str:
        return vtr_period_label(self._vtr_period_dates())

    @property
    def market_entries_in_period(self) -> list[TourEntry]:
        vtr_dates = self._vtr_period_dates()
        if not vtr_dates:
            return self.market_entries
        matched = [
            e for e in self.market_entries
            if schedules_overlap_vtr_period(vtr_dates, e.lich_kh)
        ]
        return matched if matched else self.market_entries

    @property
    def vtr_price_entries(self) -> list[TourEntry]:
        """Tour VTR dùng để TÍNH GIÁ: chỉ Dòng tour Tiết kiệm/Giá Tốt.
        Rollout-safe: nếu segment chưa có dữ liệu Dòng tour nào (chưa scrape lại) → dùng tất cả."""
        ents = self.vtr_entries
        if not any((e.dong_tour or "").strip() for e in ents):
            return ents
        return [e for e in ents if _norm_tier(e.dong_tour) in VTR_PRICE_TIERS]

    @property
    def market_price_entries(self) -> list[TourEntry]:
        """Tour thị trường dùng để TÍNH GIÁ SO SÁNH: chỉ phân khúc Premium (≈ TB tuyến).
        Rollout-safe: nếu chưa tour nào có phân khúc → dùng tất cả."""
        ents = self.market_entries_in_period
        if not any((e.phan_khuc or "").strip() for e in ents):
            return ents
        return [e for e in ents if _norm_tier(e.phan_khuc) in MARKET_PRICE_PHAN_KHUC]

    def _entries_freq_total(self, entries: list[TourEntry], *, in_vtr_period: bool = False) -> float:
        vtr_dates = self._vtr_period_dates()
        total = 0.0
        for e in entries:
            if in_vtr_period and vtr_dates:
                total += parse_departure_frequency_in_period(e.lich_kh, vtr_dates)["monthly_estimate"]
            else:
                total += e.freq_score
        return total

    def _full_price_stats(self, entries: list[TourEntry], *, vtr: bool) -> dict:
        if not entries:
            return {"weighted_avg": None, "weighted_days": None}
        vtr_dates = self._vtr_period_dates()
        weights = _departure_weights(entries, vtr_dates, in_vtr_period=True)
        avg_day = _route_avg_price_per_day(entries, weights)
        avg_days = _route_avg_days(entries, weights)
        return {
            "weighted_avg": _route_total_price(avg_day, avg_days),
            "weighted_days": avg_days,
        }

    def _price_stats(
        self,
        entries: list[TourEntry],
        *,
        vtr: bool = False,
        use_route_formula: bool = True,
    ) -> dict:
        if not entries:
            return {"avg": None, "median": None, "min": None, "max": None, "weighted_avg": None}
        prices = [e.price_day for e in entries]
        weighted_avg = None
        if use_route_formula:
            weights = _departure_weights(entries, self._vtr_period_dates(), in_vtr_period=True)
            weighted_avg = _route_avg_price_per_day(entries, weights)
        else:
            weighted_avg = _smart_day_avg(entries, vtr=vtr)
        return {
            "avg": round(sum(prices) / len(prices), 0),
            "median": _median(prices),
            "min": round(min(prices), 0),
            "max": round(max(prices), 0),
            "weighted_avg": weighted_avg,
        }

    def _freq_total(self, entries: list[TourEntry]) -> float:
        return sum(e.freq_score for e in entries)

    def _companies(self, *, in_vtr_period: bool = False) -> dict[str, CompanySegmentStats]:
        by_co: dict[str, list[TourEntry]] = defaultdict(list)
        vtr_dates = self._vtr_period_dates()
        for e in self.entries:
            if in_vtr_period and vtr_dates and not e.is_vietravel:
                if not schedules_overlap_vtr_period(vtr_dates, e.lich_kh):
                    continue
            by_co[e.cong_ty].append(e)
        result = {}
        for co, ents in by_co.items():
            ps = self._price_stats(ents, vtr=is_vietravel(co))
            freq_total = self._entries_freq_total(ents, in_vtr_period=in_vtr_period)
            result[co] = CompanySegmentStats(
                cong_ty=co,
                tour_count=len(ents),
                freq_monthly=freq_total,
                avg_departures_per_month=round(freq_total / len(ents), 1) if ents else 0,
                avg_price_day=ps["weighted_avg"],
                median_price_day=ps["median"],
                min_price_day=ps["min"],
                max_price_day=ps["max"],
            )
        return result

    @property
    def vietravel_avg_day(self) -> float | None:
        entries = self.vtr_price_entries
        if not entries:
            return None
        weights = _departure_weights(entries, self._vtr_period_dates(), in_vtr_period=True)
        return _route_avg_price_per_day(entries, weights)

    @property
    def market_avg_day(self) -> float | None:
        entries = self.market_price_entries
        if not entries:
            return None
        weights = _departure_weights(entries, self._vtr_period_dates(), in_vtr_period=True)
        return _route_avg_price_per_day(entries, weights)

    @property
    def vtr_avg_price(self) -> float | None:
        return _route_total_price(self.vietravel_avg_day, self.vtr_avg_days)

    @property
    def vtr_avg_days(self) -> float | None:
        entries = self.vtr_price_entries
        if not entries:
            return None
        weights = _departure_weights(entries, self._vtr_period_dates(), in_vtr_period=True)
        days = _route_avg_days(entries, weights)
        return _safe_num(days)

    @property
    def market_avg_days(self) -> float | None:
        entries = self.market_price_entries
        if not entries:
            return None
        weights = _departure_weights(entries, self._vtr_period_dates(), in_vtr_period=True)
        days = _route_avg_days(entries, weights)
        return _safe_num(days)

    @property
    def market_total_price(self) -> float | None:
        return _route_total_price(self.market_avg_day, self.market_avg_days)

    @property
    def comparison_price(self) -> float | None:
        """Giá so sánh = Giá TB ngày TT × Số ngày TB VTR."""
        d = self.market_avg_day
        days = self.vtr_avg_days
        if d is None or days is None:
            return None
        return round(d * days, 0)

    @property
    def gap_pct(self) -> float | None:
        v, c = self.vtr_avg_price, self.comparison_price
        if v is None or c is None or c == 0:
            return None
        return round((v / c - 1) * 100, 1)

    def _vtr_cheapest(self) -> dict | None:
        entries = self.vtr_price_entries
        if not entries:
            return None
        with_link = [e for e in entries if (e.link_url or "").strip()]
        pool = with_link if with_link else entries
        e = min(pool, key=lambda x: x.gia)
        return {
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "link_url": e.link_url or "",
            "ten_tour": e.ten_tour,
        }

    def _market_cheapest_matched(self) -> dict | None:
        matched = self.market_price_entries
        if not matched:
            return None
        vtr_dates = self._vtr_period_dates()
        has_explicit = len(vtr_dates) > 0
        with_link = [e for e in matched if (e.link_url or "").strip()]
        pool = with_link if with_link else matched
        e = min(pool, key=lambda x: x.gia)
        return {
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "link_url": e.link_url or "",
            "ten_tour": e.ten_tour,
            "cong_ty": e.cong_ty,
            "lich_kh": e.lich_kh,
            "period_matched": has_explicit,
            "has_link": bool((e.link_url or "").strip()),
        }

    @property
    def vtr_freq_monthly(self) -> float:
        return self._entries_freq_total(self.vtr_entries, in_vtr_period=True)

    @property
    def market_freq_monthly(self) -> float:
        return self._entries_freq_total(self.market_entries_in_period, in_vtr_period=True)

    def _top_freq_competitor(self) -> tuple[str, float] | None:
        """Đối thủ có TB đoàn/tháng cao nhất trên tuyến trong giai đoạn VTR."""
        from classification import resolve_company_name

        best_co = ""
        best_avg = 0.0
        for co, c in self._companies(in_vtr_period=True).items():
            if is_vietravel(co) or c.avg_departures_per_month <= 0:
                continue
            if c.avg_departures_per_month > best_avg:
                best_avg = c.avg_departures_per_month
                best_co = resolve_company_name(co)
        return (best_co, best_avg) if best_co and best_avg > 0 else None

    @property
    def freq_gap_pct(self) -> float | None:
        """VTR TB đoàn/tháng/sản phẩm so với đối thủ có tần suất cao nhất trên tuyến."""
        vtr_avg = self.vtr_avg_departures_per_month
        top = self._top_freq_competitor()
        if not top or vtr_avg <= 0:
            return None
        return round((vtr_avg / top[1] - 1) * 100, 1)

    @property
    def vtr_avg_departures_per_month(self) -> float:
        if not self.vtr_entries:
            return 0.0
        return round(self.vtr_freq_monthly / len(self.vtr_entries), 1)

    @property
    def market_freq_avg_per_company(self) -> float | None:
        comps = [c for co, c in self._companies(in_vtr_period=True).items() if not is_vietravel(co)]
        if not comps:
            return None
        avgs = [c.avg_departures_per_month for c in comps if c.tour_count > 0]
        if not avgs:
            return None
        return round(sum(avgs) / len(avgs), 1)

    def to_dict(self) -> dict:
        companies = self._companies(in_vtr_period=True)
        top_competitors = sorted(
            [c.to_dict() for co, c in companies.items() if not is_vietravel(co)],
            key=lambda x: x["freq_monthly"],
            reverse=True,
        )[:5]
        vtr_co = companies.get(COMPANY) or next(
            (c for co, c in companies.items() if is_vietravel(co)), None
        )
        vtr_min = self._vtr_cheapest()
        mkt_min = self._market_cheapest_matched()
        top_freq = self._top_freq_competitor()
        route_days = self.vtr_avg_days
        return {
            "segment_key": self.key,
            "thi_truong": self.thi_truong,
            "tuyen_tour": self.tuyen_tour,
            "diem_kh": self.diem_kh,
            "so_ngay": route_days if route_days is not None else self.so_ngay,
            "vietravel_avg_price": _safe_num(self.vtr_avg_price),
            "vietravel_avg_days": route_days,
            "vietravel_min_price": _safe_num(vtr_min["gia"]) if vtr_min else None,
            "vietravel_min_link": vtr_min["link_url"] if vtr_min else "",
            "vietravel_min_tour": vtr_min["ten_tour"] if vtr_min else "",
            "market_total_price": _safe_num(self.market_total_price),
            "comparison_price": _safe_num(self.comparison_price),
            "market_min_price": _safe_num(mkt_min["gia"]) if mkt_min else None,
            "market_min_link": mkt_min["link_url"] if mkt_min else "",
            "market_min_tour": mkt_min["ten_tour"] if mkt_min else "",
            "market_min_company": mkt_min["cong_ty"] if mkt_min else "",
            "market_min_has_link": mkt_min.get("has_link", False) if mkt_min else False,
            "vtr_comparison_period": self.vtr_comparison_period,
            "market_count_in_period": len(self.market_entries_in_period),
            "market_avg_day": _safe_num(self.market_avg_day),
            "market_avg_days": _safe_num(self.market_avg_days),
            "vietravel_avg_day": _safe_num(self.vietravel_avg_day),
            "vietravel_median_day": _safe_num(self._price_stats(self.vtr_price_entries)["median"]),
            "market_median_day": _safe_num(self._price_stats(self.market_price_entries)["median"]),
            "gap_pct": _safe_num(self.gap_pct),
            "vietravel_count": len(self.vtr_entries),
            "market_count": len(self.market_entries),
            "vietravel_freq_monthly": _safe_num(round(self.vtr_freq_monthly, 1)),
            "vtr_avg_departures_per_month": _safe_num(self.vtr_avg_departures_per_month),
            "market_freq_monthly": _safe_num(round(self.market_freq_monthly, 1)),
            "market_freq_avg_per_company": _safe_num(self.market_freq_avg_per_company),
            "top_freq_competitor": top_freq[0] if top_freq else "",
            "top_freq_competitor_departures": _safe_num(top_freq[1]) if top_freq else None,
            "freq_gap_pct": _safe_num(self.freq_gap_pct),
            "position": _position_label(self.gap_pct),
            "freq_position": _freq_position_label(self.freq_gap_pct),
            "top_competitors": top_competitors,
            "vietravel_stats": vtr_co.to_dict() if vtr_co else None,
        }


def _position_label(gap: float | None) -> str:
    if gap is None:
        return "N/A"
    if gap <= -5:
        return "Rẻ hơn TT"
    if gap >= 5:
        return "Đắt hơn TT"
    return "Tương đương"


def _freq_position_label(gap: float | None) -> str:
    if gap is None:
        return "N/A"
    if gap <= -20:
        return "Ít đoàn hơn TB"
    if gap >= 20:
        return "Nhiều đoàn hơn TB"
    return "Tương đương"


def _tour_to_entry(t: Tour, days: float) -> TourEntry | None:
    from link_utils import normalize_tour_link

    gia = _sanitize_tour_price(t.gia)
    days = _sanitize_tour_days(days) or 0
    if gia is None or days <= 0:
        return None

    freq = parse_departure_frequency(t.lich_kh)
    link = normalize_tour_link(t.link_url)
    if not link and t.ma_tour and _vtr_flag_for_compare(t):
        link = f"https://travel.com.vn/tour/{t.ma_tour.strip()}"
    return TourEntry(
        tour_id=t.id,
        cong_ty=t.cong_ty or "",
        ten_tour=t.ten_tour or "",
        gia=gia,
        gia_raw=t.gia_raw or "",
        so_ngay=days,
        price_day=round(gia / days, 0) if days else 0,
        freq_score=freq["monthly_estimate"],
        freq_label=freq["label"],
        lich_kh=t.lich_kh or "",
        lich_trinh=t.lich_trinh or "",
        link_url=link,
        thoi_gian=t.thoi_gian or "",
        is_vietravel=_vtr_flag_for_compare(t),
        phan_khuc=getattr(t, "phan_khuc", "") or "",
        dong_tour=getattr(t, "dong_tour", "") or "",
    )


def _vtr_flag_for_compare(t: Tour) -> bool:
    from tour_sources import is_vietravel_tab

    return is_vietravel_tab(t)


def build_segment_stats(tours: list[Tour], *, dedup: bool = True) -> list[SegmentStats]:
    if dedup:
        tours = deduplicate_tours(tours)
    buckets: dict[str, SegmentStats] = {}

    for t in tours:
        key = segment_key(t)
        if not key:
            continue
        days = parse_duration_days(t.thoi_gian, t.so_ngay) or 0
        if key not in buckets:
            market = (t.thi_truong or "").strip() or "Khác"
            buckets[key] = SegmentStats(
                key=key,
                thi_truong=market,
                tuyen_tour=route_for_segment(t),
                diem_kh=normalize_departure(t.diem_kh),
                so_ngay=0,
            )
        entry = _tour_to_entry(t, days)
        if entry is not None:
            buckets[key].entries.append(entry)

    return [s for s in buckets.values() if s.vtr_entries]


def summarize_context(tours: list[Tour], segments: list[SegmentStats]) -> dict:
    """KPI tổng hợp dùng CHUNG cho So sánh VTR, Trang chủ CI và Báo cáo BGĐ.

    Một nguồn tính duy nhất → 3 module luôn khớp số liệu. Định nghĩa giống compare_summary:
    rẻ ≤ -5%, đắt ≥ +5%, dẫn đầu tần suất ≥ +20%, tụt tần suất ≤ -20%.
    """
    from tour_sources import is_vietravel_tab

    cheaper = expensive = similar = freq_lead = freq_lag = 0
    gaps: list[float] = []
    vtr_freq = market_freq = 0.0
    for s in segments:
        g = s.gap_pct
        if g is not None:
            gaps.append(g)
            if g <= -5:
                cheaper += 1
            elif g >= 5:
                expensive += 1
            else:
                similar += 1
        vtr_freq += s.vtr_freq_monthly
        market_freq += s.market_freq_monthly
        fg = s.freq_gap_pct
        if fg is not None:
            if fg >= 20:
                freq_lead += 1
            elif fg <= -20:
                freq_lag += 1

    vtr_count = sum(1 for t in tours if is_vietravel_tab(t))
    market_count = sum(1 for t in tours if not is_vietravel_tab(t))
    return {
        "total_tours": len(tours),
        "vtr_count": vtr_count,
        "market_count": market_count,
        "segment_count": len(segments),
        "cheaper": cheaper,
        "expensive": expensive,
        "similar": similar,
        "avg_gap_pct": round(sum(gaps) / len(gaps), 1) if gaps else None,
        "vtr_freq_monthly": round(vtr_freq, 1),
        "market_freq_monthly": round(market_freq, 1),
        "freq_leading": freq_lead,
        "freq_lagging": freq_lag,
    }


def build_competitor_overview(tours: list[Tour], competitor: str) -> dict:
    """Profile đối thủ dùng cùng engine so sánh với Vietravel."""
    from classification import resolve_company_name

    tours = deduplicate_tours(tours)
    segments = build_segment_stats(tours, dedup=False)
    comp_canonical = resolve_company_name(competitor)
    comp_lower = comp_canonical.strip().lower()
    comp_tours = [t for t in tours if resolve_company_name(t.cong_ty).lower() == comp_lower]

    overlap_segments = []
    for seg in segments:
        comp_in_seg = [
            e for e in seg.entries
            if resolve_company_name(e.cong_ty).lower() == comp_lower and not e.is_vietravel
        ]
        if not comp_in_seg:
            continue
        vtr_dates = seg._vtr_period_dates()
        if vtr_dates:
            comp_in_seg = [
                e for e in comp_in_seg
                if schedules_overlap_vtr_period(vtr_dates, e.lich_kh)
            ] or comp_in_seg
        comp_ps = seg._price_stats(comp_in_seg, vtr=False)
        comp_compare_price = None
        if comp_ps["weighted_avg"] and seg.vtr_avg_days:
            comp_compare_price = round(comp_ps["weighted_avg"] * seg.vtr_avg_days, 0)
        comp_freq_total = seg._entries_freq_total(comp_in_seg, in_vtr_period=True)
        comp_avg_dep = round(comp_freq_total / len(comp_in_seg), 1) if comp_in_seg else 0
        overlap_segments.append({
            "segment_key": seg.key,
            "tuyen_tour": seg.tuyen_tour,
            "diem_kh": seg.diem_kh,
            "thi_truong": seg.thi_truong,
            "vtr_comparison_period": seg.vtr_comparison_period,
            "comp_avg_day": comp_ps["weighted_avg"],
            "comp_compare_price": comp_compare_price,
            "comp_freq_monthly": round(comp_freq_total, 1),
            "comp_avg_departures_per_month": comp_avg_dep,
            "vtr_avg_price": seg.vtr_avg_price,
            "price_gap_pct": _gap(seg.vtr_avg_price, comp_compare_price),
            "freq_gap_pct": _gap(seg.vtr_avg_departures_per_month, comp_avg_dep),
            "comp_tour_count": len(comp_in_seg),
            "vtr_avg_departures_per_month": seg.vtr_avg_departures_per_month,
        })

    comp_entries = [
        e
        for t in comp_tours
        if t.gia
        for e in [_tour_to_entry(t, parse_duration_days(t.thoi_gian, t.so_ngay) or 1)]
        if e is not None
    ]
    total_freq = sum(e.freq_score for e in comp_entries)
    avg_day = _smart_day_avg(comp_entries, vtr=False) if comp_entries else None

    markets: dict[str, int] = defaultdict(int)
    for t in comp_tours:
        markets[t.thi_truong or "Khác"] += 1

    return {
        "competitor": competitor,
        "total_tours": len(comp_tours),
        "avg_price_day": avg_day,
        "total_freq_monthly": round(total_freq, 1),
        "overlap_segments": len(overlap_segments),
        "markets": sorted([{"label": k, "value": v} for k, v in markets.items()], key=lambda x: -x["value"])[:10],
        "segments": sorted(overlap_segments, key=lambda x: abs(x.get("price_gap_pct") or 0), reverse=True)[:50],
        "tours": [
            {
                "id": t.id,
                "ten_tour": t.ten_tour,
                "thi_truong": t.thi_truong,
                "tuyen_tour": t.tuyen_tour,
                "gia": t.gia,
                "gia_raw": t.gia_raw,
                "lich_kh": t.lich_kh,
                "link_url": t.link_url,
            }
            for t in comp_tours[:100]
        ],
    }


def _gap(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1) * 100, 1)


def build_weekday_distribution(tours: list[Tour], *, dedup: bool = True) -> dict:
    """Phân bổ đoàn KH theo thứ — VTR vs thị trường (cùng bộ lọc compare)."""
    from departure_parser import WEEKDAY_LABELS, parse_departure_frequency, parse_weekday_slots

    if dedup:
        tours = deduplicate_tours(tours)

    vtr_weights = [0.0] * 7
    mkt_weights = [0.0] * 7
    vtr_tours = mkt_tours = 0

    for t in tours:
        if not t.gia or t.gia <= 0:
            continue
        days = parse_duration_days(t.thoi_gian, t.so_ngay)
        if not days:
            continue
        slots = parse_weekday_slots(t.lich_kh or "")
        if not slots:
            continue
        slot_total = sum(slots.values())
        if slot_total <= 0:
            continue
        freq = parse_departure_frequency(t.lich_kh or "")["monthly_estimate"]
        bucket = vtr_weights if is_vietravel(t.cong_ty) else mkt_weights
        if is_vietravel(t.cong_ty):
            vtr_tours += 1
        else:
            mkt_tours += 1
        for wd, cnt in slots.items():
            if 0 <= wd <= 6:
                bucket[wd] += freq * (cnt / slot_total)

    def _rows(weights: list[float]) -> list[dict]:
        total = sum(weights)
        rows = []
        for i, label in enumerate(WEEKDAY_LABELS):
            value = round(weights[i], 1)
            rows.append({
                "weekday": label,
                "weekday_index": i,
                "departures_monthly": value,
                "share_pct": round(value / total * 100, 1) if total > 0 else 0.0,
            })
        return rows

    return {
        "labels": WEEKDAY_LABELS,
        "vietravel": _rows(vtr_weights),
        "market": _rows(mkt_weights),
        "vietravel_total": round(sum(vtr_weights), 1),
        "market_total": round(sum(mkt_weights), 1),
        "vietravel_tour_count": vtr_tours,
        "market_tour_count": mkt_tours,
    }


METHODOLOGY = (
    "Nhóm so sánh = cùng Thị trường + Tuyến tour + Điểm khởi hành (gộp mọi sản phẩm/thời gian trên tuyến). "
    "Trọng số mỗi sản phẩm = số đoàn khởi hành (ưu tiên đếm ngày KH trong giai đoạn VTR). "
    "Số ngày TB VTR = Σ(đoàn × ngày) ÷ Σ(đoàn). "
    "Giá TB/ngày VTR = Σ(giá tour × đoàn) ÷ Σ(đoàn × ngày). "
    "Giá TB tour VTR = Giá TB/ngày VTR × Số ngày TB VTR. "
    "Giá TB/ngày TT = Σ(giá tour × đoàn) ÷ Σ(đoàn × ngày) của đối thủ cùng giai đoạn KH. "
    "Giá so sánh = Giá TB/ngày TT × Số ngày TB VTR. "
    "Chênh % = Giá TB tour VTR ÷ Giá so sánh − 1."
)
