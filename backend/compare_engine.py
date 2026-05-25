"""So sánh Vietravel vs thị trường & đối thủ — giá/ngày + tần suất KH theo segment."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from config import settings
from departure_parser import parse_departure_frequency, parse_departure_dates, schedules_overlap_vtr_period
from models import Tour

COMPANY = settings.company_name
NGUON_PRIORITY = {"FindTourGo": 3, "Vietravel": 2, "Main": 1, "Manual": 0}

DEPART_ALIASES: list[tuple[str, str]] = [
    ("hồ chí minh", "TP.HCM"), ("tp.hcm", "TP.HCM"), ("tp hcm", "TP.HCM"),
    ("sài gòn", "TP.HCM"), ("sai gon", "TP.HCM"), ("tphcm", "TP.HCM"), ("hcm", "TP.HCM"),
    ("hà nội", "Hà Nội"), ("ha noi", "Hà Nội"),
    ("đà nẵng", "Đà Nẵng"), ("da nang", "Đà Nẵng"),
    ("cần thơ", "Cần Thơ"), ("can tho", "Cần Thơ"),
    ("nha trang", "Nha Trang"), ("huế", "Huế"),
    ("hải phòng", "Hải Phòng"), ("vinh", "Vinh"),
]


def normalize_departure(diem_kh: str) -> str:
    s = (diem_kh or "").strip().lower()
    if not s:
        return "Khác"
    for alias, label in DEPART_ALIASES:
        if alias in s:
            return label
    head = re.split(r"[,|\-–—]", diem_kh)[0].strip()
    return head[:64] if head else "Khác"


def normalize_route(tuyen_tour: str) -> str:
    return re.sub(r"\s+", " ", (tuyen_tour or "").strip())[:256]


def is_vietravel(cong_ty: str) -> bool:
    from classification import resolve_company_name
    resolved = resolve_company_name(cong_ty or "")
    return settings.company_name.lower() in resolved.lower()


def parse_duration_days(thoi_gian: str, so_ngay: float | None) -> float | None:
    if so_ngay and 0 < so_ngay <= 45:
        return round(so_ngay, 1)
    if not thoi_gian:
        return None
    s = thoi_gian.strip().lower()
    m = re.search(r"(\d+)\s*n\s*(\d+)\s*đ", s)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*ngày", s)
    if m:
        d = float(m.group(1))
        return d if 0 < d <= 45 else None
    m = re.search(r"(\d+)\s*n\b", s)
    if m:
        d = float(m.group(1))
        return d if 0 < d <= 45 else None
    return None


def make_segment_key(thi_truong: str, route: str, depart: str, days: float) -> str:
    return f"{thi_truong}|{route}|{depart}|{days:.0f}d"


def segment_key(tour: Tour) -> str | None:
    days = parse_duration_days(tour.thoi_gian, tour.so_ngay)
    route = normalize_route(tour.tuyen_tour)
    depart = normalize_departure(tour.diem_kh)
    market = (tour.thi_truong or "").strip() or "Khác"
    if not route or not days or not tour.gia or tour.gia <= 0:
        return None
    return make_segment_key(market, route, depart, days)


def _dedup_key(t: Tour) -> str:
    ma = (t.ma_tour or "").strip().lower()
    link = (t.link_url or "").strip().lower()
    company = (t.cong_ty or "").strip().lower()
    if ma:
        return f"{company}|{ma}"
    if link:
        return f"{company}|{link}"
    return f"{company}|id:{t.id}"


def _tour_priority(t: Tour) -> tuple:
    src = NGUON_PRIORITY.get(t.nguon or "", 0)
    updated = t.updated_at.timestamp() if t.updated_at else 0
    return (src, updated)


def deduplicate_tours(tours: list[Tour]) -> list[Tour]:
    best: dict[str, Tour] = {}
    for t in tours:
        k = _dedup_key(t)
        if k not in best or _tour_priority(t) > _tour_priority(best[k]):
            best[k] = t
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


def _weighted_avg(values: list[tuple[float, float]]) -> float | None:
    if not values:
        return None
    total_w = sum(w for _, w in values)
    if total_w <= 0:
        return round(sum(v for v, _ in values) / len(values), 0)
    return round(sum(v * w for v, w in values) / total_w, 0)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 0)


@dataclass
class CompanySegmentStats:
    cong_ty: str
    tour_count: int = 0
    freq_monthly: float = 0.0
    avg_price_day: float | None = None
    median_price_day: float | None = None
    min_price_day: float | None = None
    max_price_day: float | None = None

    def to_dict(self) -> dict:
        return {
            "cong_ty": self.cong_ty,
            "tour_count": self.tour_count,
            "freq_monthly": round(self.freq_monthly, 1),
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

    def _full_price_stats(self, entries: list[TourEntry]) -> dict:
        if not entries:
            return {"weighted_avg": None, "weighted_days": None}
        price_pairs = [(e.gia, e.freq_score) for e in entries]
        day_pairs = [(e.so_ngay, e.freq_score) for e in entries]
        return {
            "weighted_avg": _weighted_avg(price_pairs),
            "weighted_days": _weighted_avg(day_pairs),
        }

    def _price_stats(self, entries: list[TourEntry]) -> dict:
        if not entries:
            return {"avg": None, "median": None, "min": None, "max": None, "weighted_avg": None}
        pairs = [(e.price_day, e.freq_score) for e in entries]
        prices = [e.price_day for e in entries]
        return {
            "avg": round(sum(prices) / len(prices), 0),
            "median": _median(prices),
            "min": round(min(prices), 0),
            "max": round(max(prices), 0),
            "weighted_avg": _weighted_avg(pairs),
        }

    def _freq_total(self, entries: list[TourEntry]) -> float:
        return sum(e.freq_score for e in entries)

    def _companies(self) -> dict[str, CompanySegmentStats]:
        by_co: dict[str, list[TourEntry]] = defaultdict(list)
        for e in self.entries:
            by_co[e.cong_ty].append(e)
        result = {}
        for co, ents in by_co.items():
            ps = self._price_stats(ents)
            result[co] = CompanySegmentStats(
                cong_ty=co,
                tour_count=len(ents),
                freq_monthly=self._freq_total(ents),
                avg_price_day=ps["weighted_avg"],
                median_price_day=ps["median"],
                min_price_day=ps["min"],
                max_price_day=ps["max"],
            )
        return result

    @property
    def vietravel_avg_day(self) -> float | None:
        return self._price_stats(self.vtr_entries)["weighted_avg"]

    @property
    def market_avg_day(self) -> float | None:
        return self._price_stats(self.market_entries)["weighted_avg"]

    @property
    def vtr_avg_price(self) -> float | None:
        return self._full_price_stats(self.vtr_entries)["weighted_avg"]

    @property
    def vtr_avg_days(self) -> float | None:
        days = self._full_price_stats(self.vtr_entries)["weighted_days"]
        return round(days, 1) if days else None

    @property
    def market_avg_days(self) -> float | None:
        days = self._full_price_stats(self.market_entries)["weighted_days"]
        return round(days, 1) if days else None

    @property
    def market_total_price(self) -> float | None:
        d = self.market_avg_day
        days = self.market_avg_days
        if d is None or days is None:
            return None
        return round(d * days, 0)

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
        if not self.vtr_entries:
            return None
        e = min(self.vtr_entries, key=lambda x: x.gia)
        return {
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "link_url": e.link_url,
            "ten_tour": e.ten_tour,
        }

    def _market_cheapest_matched(self) -> dict | None:
        if not self.market_entries:
            return None
        vtr_dates: list = []
        for e in self.vtr_entries:
            vtr_dates.extend(parse_departure_dates(e.lich_kh))
        has_explicit = len(vtr_dates) > 0

        matched = [
            e for e in self.market_entries
            if schedules_overlap_vtr_period(vtr_dates, e.lich_kh)
        ] if has_explicit else list(self.market_entries)

        if not matched:
            matched = list(self.market_entries)

        e = min(matched, key=lambda x: x.gia)
        return {
            "gia": e.gia,
            "gia_raw": e.gia_raw,
            "link_url": e.link_url,
            "ten_tour": e.ten_tour,
            "cong_ty": e.cong_ty,
            "lich_kh": e.lich_kh,
            "period_matched": has_explicit,
        }

    @property
    def vtr_freq_monthly(self) -> float:
        return self._freq_total(self.vtr_entries)

    @property
    def market_freq_monthly(self) -> float:
        return self._freq_total(self.market_entries)

    @property
    def freq_gap_pct(self) -> float | None:
        """VTR tần suất so với TB tần suất mỗi đối thủ trong segment."""
        vtr_f = self.vtr_freq_monthly
        comps = [c for co, c in self._companies().items() if not is_vietravel(co)]
        if not comps or vtr_f <= 0:
            return None
        avg_comp_freq = sum(c.freq_monthly for c in comps) / len(comps)
        if avg_comp_freq <= 0:
            return None
        return round((vtr_f / avg_comp_freq - 1) * 100, 1)

    @property
    def market_freq_avg_per_company(self) -> float | None:
        comps = [c for co, c in self._companies().items() if not is_vietravel(co)]
        if not comps:
            return None
        return round(sum(c.freq_monthly for c in comps) / len(comps), 1)

    def to_dict(self) -> dict:
        companies = self._companies()
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
        return {
            "segment_key": self.key,
            "thi_truong": self.thi_truong,
            "tuyen_tour": self.tuyen_tour,
            "diem_kh": self.diem_kh,
            "so_ngay": self.so_ngay,
            "vietravel_avg_price": self.vtr_avg_price,
            "vietravel_avg_days": self.vtr_avg_days,
            "vietravel_min_price": vtr_min["gia"] if vtr_min else None,
            "vietravel_min_link": vtr_min["link_url"] if vtr_min else "",
            "vietravel_min_tour": vtr_min["ten_tour"] if vtr_min else "",
            "market_total_price": self.market_total_price,
            "comparison_price": self.comparison_price,
            "market_min_price": mkt_min["gia"] if mkt_min else None,
            "market_min_link": mkt_min["link_url"] if mkt_min else "",
            "market_min_tour": mkt_min["ten_tour"] if mkt_min else "",
            "market_min_company": mkt_min["cong_ty"] if mkt_min else "",
            "market_avg_day": self.market_avg_day,
            "market_avg_days": self.market_avg_days,
            "vietravel_avg_day": self.vietravel_avg_day,
            "vietravel_median_day": self._price_stats(self.vtr_entries)["median"],
            "market_median_day": self._price_stats(self.market_entries)["median"],
            "gap_pct": self.gap_pct,
            "vietravel_count": len(self.vtr_entries),
            "market_count": len(self.market_entries),
            "vietravel_freq_monthly": round(self.vtr_freq_monthly, 1),
            "market_freq_monthly": round(self.market_freq_monthly, 1),
            "market_freq_avg_per_company": self.market_freq_avg_per_company,
            "freq_gap_pct": self.freq_gap_pct,
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
    return "Tần suất tương đương"


def _tour_to_entry(t: Tour, days: float) -> TourEntry:
    freq = parse_departure_frequency(t.lich_kh)
    return TourEntry(
        tour_id=t.id,
        cong_ty=t.cong_ty or "",
        ten_tour=t.ten_tour or "",
        gia=t.gia or 0,
        gia_raw=t.gia_raw or "",
        so_ngay=days,
        price_day=round((t.gia or 0) / days, 0),
        freq_score=freq["monthly_estimate"],
        freq_label=freq["label"],
        lich_kh=t.lich_kh or "",
        lich_trinh=t.lich_trinh or "",
        link_url=t.link_url or "",
        thoi_gian=t.thoi_gian or "",
        is_vietravel=is_vietravel(t.cong_ty),
    )


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
                tuyen_tour=normalize_route(t.tuyen_tour),
                diem_kh=normalize_departure(t.diem_kh),
                so_ngay=days,
            )
        buckets[key].entries.append(_tour_to_entry(t, days))

    return [s for s in buckets.values() if s.vtr_entries]


def build_competitor_overview(tours: list[Tour], competitor: str) -> dict:
    """Profile đối thủ dùng cùng engine so sánh với Vietravel."""
    tours = deduplicate_tours(tours)
    segments = build_segment_stats(tours, dedup=False)
    comp_lower = competitor.strip().lower()
    comp_tours = [t for t in tours if (t.cong_ty or "").lower() == comp_lower]

    overlap_segments = []
    for seg in segments:
        comp_in_seg = [e for e in seg.entries if e.cong_ty.lower() == comp_lower]
        if not comp_in_seg:
            continue
        vtr = seg.vtr_entries
        comp_ps = seg._price_stats(comp_in_seg)
        comp_compare_price = None
        if comp_ps["weighted_avg"] and seg.vtr_avg_days:
            comp_compare_price = round(comp_ps["weighted_avg"] * seg.vtr_avg_days, 0)
        overlap_segments.append({
            "segment_key": seg.key,
            "tuyen_tour": seg.tuyen_tour,
            "diem_kh": seg.diem_kh,
            "so_ngay": seg.so_ngay,
            "thi_truong": seg.thi_truong,
            "comp_avg_day": comp_ps["weighted_avg"],
            "comp_compare_price": comp_compare_price,
            "comp_freq_monthly": round(sum(e.freq_score for e in comp_in_seg), 1),
            "vtr_avg_price": seg.vtr_avg_price,
            "vtr_avg_days": seg.vtr_avg_days,
            "vtr_freq_monthly": round(seg.vtr_freq_monthly, 1),
            "price_gap_pct": _gap(seg.vtr_avg_price, comp_compare_price),
            "freq_gap_pct": _gap(seg.vtr_freq_monthly, sum(e.freq_score for e in comp_in_seg)),
            "comp_tour_count": len(comp_in_seg),
        })

    comp_entries = [_tour_to_entry(t, parse_duration_days(t.thoi_gian, t.so_ngay) or 1) for t in comp_tours if t.gia]
    total_freq = sum(e.freq_score for e in comp_entries)
    avg_day = _weighted_avg([(e.price_day, e.freq_score) for e in comp_entries])

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


METHODOLOGY = (
    "Segment = cùng Thị trường + Tuyến tour + Điểm KH + Số ngày. "
    "Giá TB VTR = trung bình có trọng số theo tần suất KH. "
    "Giá thị trường = Giá TB ngày TT × Số ngày TB TT. "
    "Giá so sánh = Giá TB ngày TT × Số ngày TB VTR. "
    "Chênh % = (Giá TB VTR ÷ Giá so sánh − 1) × 100. "
    "Tour rẻ nhất TT: cùng giai đoạn KH với VTR (cùng tháng hoặc ±45 ngày). "
    "Loại trùng theo mã tour/link."
)
