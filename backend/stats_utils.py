"""Thống kê giá có trọng số — giảm ảnh hưởng outlier (luxury vs phổ thông)."""
from __future__ import annotations

CV_THRESHOLD = 0.40
SPREAD_THRESHOLD = 2.5
TRIM_RATIO = 0.10


def weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return round(sum(v for v, _ in pairs) / len(pairs), 0)
    return round(sum(v * w for v, w in pairs) / total_w, 0)


def weighted_median(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    sorted_pairs = sorted(pairs, key=lambda x: x[0])
    total_w = sum(w for _, w in sorted_pairs)
    if total_w <= 0:
        mid = len(sorted_pairs) // 2
        return round(sorted_pairs[mid][0], 0)
    half = total_w / 2
    acc = 0.0
    for v, w in sorted_pairs:
        acc += w
        if acc >= half:
            return round(v, 0)
    return round(sorted_pairs[-1][0], 0)


def trimmed_weighted_avg(pairs: list[tuple[float, float]], trim_ratio: float = TRIM_RATIO) -> float | None:
    if len(pairs) <= 2:
        return weighted_avg(pairs)
    sorted_pairs = sorted(pairs, key=lambda x: x[0])
    total_w = sum(w for _, w in sorted_pairs)
    trim_w = total_w * trim_ratio
    remaining = list(sorted_pairs)
    bottom = 0.0
    while remaining and bottom < trim_w:
        bottom += remaining[0][1]
        remaining.pop(0)
    top = 0.0
    while remaining and top < trim_w:
        top += remaining[-1][1]
        remaining.pop()
    return weighted_avg(remaining) if remaining else weighted_avg(pairs)


def _weighted_cv(pairs: list[tuple[float, float]], mean: float) -> float:
    total_w = sum(w for _, w in pairs)
    if total_w <= 0 or mean <= 0:
        return 0.0
    var = sum(w * (v - mean) ** 2 for v, w in pairs) / total_w
    return (var ** 0.5) / mean


def robust_weighted_avg(pairs: list[tuple[float, float]]) -> float | None:
    """
    TB có trọng số theo số đoàn/tháng.
    Khi biên độ giá quá lớn (CV > 40% hoặc max/min > 2.5×): cắt 10% hai đầu + pha trộn median.
    """
    if not pairs:
        return None
    if len(pairs) < 3:
        return weighted_avg(pairs)

    base = weighted_avg(pairs)
    if base is None:
        return None

    values = [v for v, _ in pairs if v > 0]
    cv = _weighted_cv(pairs, base)
    spread = max(values) / min(values) if values and min(values) > 0 else 1.0

    if cv <= CV_THRESHOLD and spread <= SPREAD_THRESHOLD:
        return base

    trimmed = trimmed_weighted_avg(pairs)
    med = weighted_median(pairs)
    if trimmed and med:
        return round(0.65 * trimmed + 0.35 * med, 0)
    return trimmed or med or base
