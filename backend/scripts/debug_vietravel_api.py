"""Dump cấu trúc response API Vietravel mới (api2.travel.com.vn).

Vietravel đổi web sang SPA → data qua API JSON, không còn nhúng HTML.
Script này gọi API thật + in cấu trúc 1-2 tour để biết tên field (giá/tên/điểm KH/
dòng tour/thời gian) → phục vụ viết lại vietravel_scraper.py.

Usage (backend root):
    python scripts/debug_vietravel_api.py
    python scripts/debug_vietravel_api.py viet-nam 5
    python scripts/debug_vietravel_api.py nhat-ban 3
"""
from __future__ import annotations

import json
import sys
from datetime import date

import requests

API_URL = "https://api2.travel.com.vn/core/tour/search-tour-file-filter"
# Token JWT tĩnh của web app (exp năm 9999) — public key baked vào site travel.com.vn.
BEARER = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJuIjoid2ViX3RyYXZlbCIsImMiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGIi"
    "LCJ3IjoiVHJhdmVsLmNvbS52bnxodHRwczovL3RyYXZlbC5jb20udm4iLCJwIjoiVHJhdmVsfFRyYXZlbCIs"
    "InUiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGJ8NDY5NGM2ODItNDZjNy00Y2M2LWEx"
    "OTQtOTY4ZWE5NWU5Y2M5IiwiciI6IkFkbWluIiwiZXhwIjoyNTM0MDIyNzU2MDAsImlzcyI6InRyYXZlbC5j"
    "b20udm4iLCJhdWQiOiJhYjcyOTZmMi0wNDg5LTRiNGQtODVhMi0wOTAwNmNjYjNlMGIifQ."
    "aX3hZxdsCkV4qr_0l_Z4RsAXfkMY4VBSFIb0VTobVOQ"
)
CLIENT_ID = "AB7296F2-0489-4B4D-85A2-09006CCB3E0B"

HEADERS = {
    "accept": "application/json",
    "accept-language": "vi",
    "authorization": f"Bearer {BEARER}",
    "clientid": CLIENT_ID,
    "client-url": "https://travel.com.vn/du-lich-viet-nam.aspx",
    "content-type": "application/json",
    "origin": "https://travel.com.vn",
    "referer": "https://travel.com.vn/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
}


def _walk_keys(obj, prefix="", out=None, depth=0):
    """Liệt kê path các key (để thấy field lồng nhau)."""
    if out is None:
        out = []
    if depth > 4:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            t = type(v).__name__
            sample = ""
            if isinstance(v, (str, int, float, bool)) or v is None:
                sample = f" = {v!r}"[:80]
            out.append(f"{p} ({t}){sample}")
            _walk_keys(v, p, out, depth + 1)
    elif isinstance(obj, list) and obj:
        out.append(f"{prefix}[] (list, len={len(obj)})")
        _walk_keys(obj[0], f"{prefix}[0]", out, depth + 1)
    return out


def main(argv):
    keywords = argv[1] if len(argv) > 1 else "viet-nam"
    page_size = int(argv[2]) if len(argv) > 2 else 3
    body = {"fromDate": date.today().isoformat(), "keywords": keywords}
    params = {"page": 0, "pageSize": page_size}

    print(f"POST {API_URL}?page=0&pageSize={page_size}")
    print(f"BODY {body}")
    print("=" * 80)
    try:
        r = requests.post(API_URL, params=params, json=body, headers=HEADERS, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"REQUEST FAILED: {e}")
        return 1
    print(f"STATUS {r.status_code}  len={len(r.content)}")
    if r.status_code != 200:
        print(r.text[:2000])
        return 1
    data = r.json()

    # Top-level structure
    print("\n--- TOP-LEVEL KEYS ---")
    if isinstance(data, dict):
        for k, v in data.items():
            t = type(v).__name__
            extra = f" len={len(v)}" if isinstance(v, (list, dict)) else f" = {v!r}"[:60]
            print(f"  {k} ({t}){extra}")

    # Tìm list tour (key chứa list dict có vẻ là tour)
    tour_list = None
    container = data if isinstance(data, dict) else {}
    for k, v in container.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            tour_list = v
            print(f"\n>>> List tour có vẻ ở key: {k!r} (len={len(v)})")
            break
        if isinstance(v, dict):  # data lồng 1 cấp (vd data.items)
            for k2, v2 in v.items():
                if isinstance(v2, list) and v2 and isinstance(v2[0], dict):
                    tour_list = v2
                    print(f"\n>>> List tour có vẻ ở key: {k}.{k2!r} (len={len(v2)})")
                    break
        if tour_list:
            break

    if not tour_list:
        print("\n!!! Không tìm thấy list tour — dump 3000 ký tự đầu:")
        print(json.dumps(data, ensure_ascii=False)[:3000])
        return 0

    print("\n--- KEY PATHS CỦA 1 TOUR ---")
    for line in _walk_keys(tour_list[0]):
        print(f"  {line}")

    print("\n--- FULL JSON TOUR ĐẦU TIÊN (pretty) ---")
    print(json.dumps(tour_list[0], ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
