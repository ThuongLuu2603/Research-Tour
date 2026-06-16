"""Merge canonical tour data with per-workspace user overrides."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from models import Tour, TourOverride

OVERRIDE_FIELDS = frozenset({
    "cong_ty", "thi_truong", "tuyen_tour", "diem_kh", "thoi_gian", "analyst_note", "flagged",
})

# Các field text mà override="" KHÔNG được phép wipe giá trị canonical khi hiển thị.
# (analyst_note/flagged được phép rỗng/false — đó là ý người dùng.)
_NON_WIPE_OVERRIDE_FIELDS = frozenset({
    "cong_ty", "thi_truong", "tuyen_tour", "diem_kh", "thoi_gian",
})


def _is_blank_override(field: str, value: Any) -> bool:
    """Override rỗng cho field text → coi như KHÔNG override (giữ canonical).

    Đây là GỐC bug diem_kh/thoi_gian bị '' khi tour không match quy tắc: form stale
    gửi chuỗi rỗng → lưu vào override → merge hiển thị '' đè lên giá trị DB đúng."""
    if field not in _NON_WIPE_OVERRIDE_FIELDS:
        return False
    return value is None or (isinstance(value, str) and not value.strip())

TOUR_EXPORT_FIELDS = (
    "id", "external_id", "cong_ty", "thi_truong", "tuyen_tour", "ten_tour",
    "lich_trinh", "diem_kh", "thoi_gian", "gia", "gia_raw", "lich_kh",
    "link_url", "ma_tour", "khach_san", "hang_khong", "so_ngay", "phan_khuc",
    "nguon", "analyst_note", "flagged", "manual_locked",
)


@dataclass
class EffectiveTour:
    tour: Tour
    overrides: dict[str, Any]
    has_override: bool

    def get(self, field: str, default: Any = "") -> Any:
        if field in self.overrides and not _is_blank_override(field, self.overrides[field]):
            return self.overrides[field]
        return getattr(self.tour, field, default)

    def to_dict(self) -> dict[str, Any]:
        out = {f: getattr(self.tour, f, None) for f in TOUR_EXPORT_FIELDS if hasattr(self.tour, f)}
        for k, v in self.overrides.items():
            if k in OVERRIDE_FIELDS and not _is_blank_override(k, v):
                out[k] = v
        # Override thời gian → tính lại số ngày để hiển thị/giá-ngày khớp trong workspace.
        if "thoi_gian" in self.overrides:
            try:
                from seed import parse_ngay
                out["so_ngay"] = parse_ngay(self.overrides["thoi_gian"])
            except Exception:
                pass
        out["dong_tour"] = getattr(self.tour, "dong_tour", "")
        # Vietravel: Dòng tour = phân khúc → hiển thị ở cột Phân khúc (kể cả khi DB phan_khuc cũ).
        if (getattr(self.tour, "nguon", "") or "") == "Vietravel" and (out["dong_tour"] or "").strip():
            out["phan_khuc"] = (out["dong_tour"] or "").strip()
        out["has_override"] = self.has_override
        # TB tần suất / tháng: số đoàn KH/tháng của tour (đếm ngày từ lich_kh qua rule
        # Định dạng Ngày KH; parse_departure_dates đã memoize nên rẻ). 0 = lich_kh
        # không khớp định dạng ngày.
        try:
            from departure_parser import parse_departure_frequency
            out["freq_monthly"] = parse_departure_frequency(getattr(self.tour, "lich_kh", "") or "")["monthly_estimate"]
        except Exception:  # noqa: BLE001
            out["freq_monthly"] = 0.0
        # CockroachDB unique_rowid() > 2^53 (JS MAX_SAFE_INTEGER). Serialize as
        # string để frontend không round mất last digits → PATCH 404.
        out["id"] = str(self.tour.id)
        out["canonical_id"] = str(self.tour.id)
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
    # Loại bỏ override rỗng cho field text → giữ canonical, tự "heal" row đã hỏng từ trước.
    filtered = {
        k: v for k, v in overrides.items()
        if k in OVERRIDE_FIELDS and not _is_blank_override(k, v)
    }
    return EffectiveTour(tour=canonical, overrides=filtered, has_override=bool(filtered))


def build_override_patch(patch: dict[str, Any]) -> dict[str, Any]:
    # STICKY: bỏ None VÀ chuỗi rỗng cho field text (diem_kh/thoi_gian/...) → không bao
    # giờ ghi override="" wipe giá trị canonical. analyst_note/flagged vẫn cho rỗng.
    out: dict[str, Any] = {}
    for k, v in patch.items():
        if k not in OVERRIDE_FIELDS or v is None:
            continue
        if _is_blank_override(k, v):
            continue
        out[k] = v
    return out
