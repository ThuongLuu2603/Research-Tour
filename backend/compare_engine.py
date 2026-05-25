"""So sánh giá Vietravel vs thị trường — chuẩn hóa giá / ngày theo tuyến + điểm KH + thời lượng."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from config import settings
from models import Tour

COMPANY = settings.company_name

# Chuẩn hóa điểm khởi hành về nhãn ngắn
DEPART_ALIASES: list[tuple[str, str]] = [
    ("hồ chí minh", "TP.HCM"),
    ("tp.hcm", "TP.HCM"),
    ("tp hcm", "TP.HCM"),
    ("sài gòn", "TP.HCM"),
    ("sai gon", "TP.HCM"),
    ("tphcm", "TP.HCM"),
    ("hcm", "TP.HCM"),
    ("hà nội", "Hà Nội"),
    ("ha noi", "Hà Nội"),
    ("đà nẵng", "Đà Nẵng"),
    ("da nang", "Đà Nẵng"),
    ("cần thơ", "Cần Thơ"),
    ("can tho", "Cần Thơ"),
    ("nha trang", "Nha Trang"),
    ("huế", "Huế"),
    ("hải phòng", "Hải Phòng"),
    ("vinh", "Vinh"),
]


def normalize_departure(diem_kh: str) -> str:
    s = (diem_kh or "").strip().lower()
    if not s:
        return "Khác"
    for alias, label in DEPART_ALIASES:
        if alias in s:
            return label
    # Lấy phần trước dấu phẩy / gạch
    head = re.split(r"[,|\-–—]", diem_kh)[0].strip()
    return head[:64] if head else "Khác"


def normalize_route(tuyen_tour: str) -> str:
    return re.sub(r"\s+", " ", (tuyen_tour or "").strip())[:256]


def is_vietravel(cong_ty: str) -> bool:
    return COMPANY.lower() in (cong_ty or "").lower()


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


def segment_key(tour: Tour) -> str | None:
    """Khóa so sánh: cùng tuyến + điểm KH + số ngày."""
    days = parse_duration_days(tour.thoi_gian, tour.so_ngay)
    route = normalize_route(tour.tuyen_tour)
    depart = normalize_departure(tour.diem_kh)
    if not route or not days or not tour.gia or tour.gia <= 0:
        return None
    return f"{route}|{depart}|{days:.0f}d"


@dataclass
class SegmentStats:
    key: str
    tuyen_tour: str
    diem_kh: str
    so_ngay: float
    thi_truong: str
    vietravel_prices_day: list[float] = field(default_factory=list)
    market_prices_day: list[float] = field(default_factory=list)
    competitor_prices_day: list[float] = field(default_factory=list)

    @property
    def vietravel_avg(self) -> float | None:
        if not self.vietravel_prices_day:
            return None
        return round(sum(self.vietravel_prices_day) / len(self.vietravel_prices_day), 0)

    @property
    def market_avg(self) -> float | None:
        if not self.market_prices_day:
            return None
        return round(sum(self.market_prices_day) / len(self.market_prices_day), 0)

    @property
    def competitor_avg(self) -> float | None:
        if not self.competitor_prices_day:
            return None
        return round(sum(self.competitor_prices_day) / len(self.competitor_prices_day), 0)

    @property
    def gap_pct(self) -> float | None:
        if self.vietravel_avg is None or self.market_avg is None or self.market_avg == 0:
            return None
        return round((self.vietravel_avg / self.market_avg - 1) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "segment_key": self.key,
            "tuyen_tour": self.tuyen_tour,
            "diem_kh": self.diem_kh,
            "so_ngay": self.so_ngay,
            "thi_truong": self.thi_truong,
            "vietravel_avg_day": self.vietravel_avg,
            "market_avg_day": self.market_avg,
            "competitor_avg_day": self.competitor_avg,
            "gap_pct": self.gap_pct,
            "vietravel_count": len(self.vietravel_prices_day),
            "market_count": len(self.market_prices_day),
            "position": _position_label(self.gap_pct),
        }


def _position_label(gap: float | None) -> str:
    if gap is None:
        return "N/A"
    if gap <= -5:
        return "Rẻ hơn thị trường"
    if gap >= 5:
        return "Đắt hơn thị trường"
    return "Tương đương"


def build_segment_stats(tours: list[Tour]) -> list[SegmentStats]:
    buckets: dict[str, SegmentStats] = {}

    for t in tours:
        key = segment_key(t)
        if not key:
            continue
        days = parse_duration_days(t.thoi_gian, t.so_ngay)
        if key not in buckets:
            segs = key.rsplit("|", 2)
            route = segs[0] if len(segs) >= 3 else key
            depart = segs[1] if len(segs) >= 3 else ""
            buckets[key] = SegmentStats(
                key=key,
                tuyen_tour=route,
                diem_kh=depart,
                so_ngay=days or 0,
                thi_truong=t.thi_truong or "",
            )
        price_day = t.gia / days  # type: ignore
        if is_vietravel(t.cong_ty):
            buckets[key].vietravel_prices_day.append(price_day)
        else:
            buckets[key].market_prices_day.append(price_day)
            buckets[key].competitor_prices_day.append(price_day)

    # Chỉ giữ segment có ít nhất 1 tour Vietravel
    return [s for s in buckets.values() if s.vietravel_prices_day]
