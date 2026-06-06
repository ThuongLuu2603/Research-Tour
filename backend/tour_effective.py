"""Merge canonical tour data with per-workspace user overrides."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from models import Tour, TourOverride

OVERRIDE_FIELDS = frozenset({
    "cong_ty", "thi_truong", "tuyen_tour", "diem_kh", "thoi_gian", "analyst_note", "flagged",
})

TOUR_EXPORT_FIELDS = (
    "id", "external_id", "cong_ty", "thi_truong", "tuyen_tour", "ten_tour",
    "lich_trinh", "diem_kh", "thoi_gian", "gia", "gia_raw", "lich_kh",
    "link_url", "ma_tour", "khach_san", "hang_khong", "so_ngay", "phan_khuc",
    "nguon", "analyst_note", "flagged",
)


@dataclass
class EffectiveTour:
    tour: Tour
    overrides: dict[str, Any]
    has_override: bool

    def get(self, field: str, default: Any = "") -> Any:
        if field in self.overrides:
            return self.overrides[field]
        return getattr(self.tour, field, default)

    def to_dict(self) -> dict[str, Any]:
        out = {f: getattr(self.tour, f, None) for f in TOUR_EXPORT_FIELDS if hasattr(self.tour, f)}
        for k, v in self.overrides.items():
            if k in OVERRIDE_FIELDS:
                out[k] = v
        # Override thời gian → tính lại số ngày để hiển thị/giá-ngày khớp trong workspace.
        if "thoi_gian" in self.overrides:
            try:
                from seed import parse_ngay
                out["so_ngay"] = parse_ngay(self.overrides["thoi_gian"])
            except Exception:
                pass
        out["dong_tour"] = getattr(self.tour, "dong_tour", "")
        out["has_override"] = self.has_override
        out["canonical_id"] = self.tour.id
        return out


def parse_override_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def merge_tour(canonical: Tour, override: TourOverride | None) -> EffectiveTour:
    overrides = parse_override_json(override.overrides_json if override else None)
    filtered = {k: v for k, v in overrides.items() if k in OVERRIDE_FIELDS}
    return EffectiveTour(tour=canonical, overrides=filtered, has_override=bool(filtered))


def build_override_patch(patch: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in patch.items() if k in OVERRIDE_FIELDS and v is not None}
