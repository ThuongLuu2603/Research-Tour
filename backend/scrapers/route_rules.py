"""
Phân loại Tuyến tour từ Thị trường + Tên tour + Lịch trình.
Nguồn quy tắc: sheet "Điểm tuyến Tour" (gid=58839224) — logic tuyen tour.md.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

SHEET_ID = "1sI34D88zsmSrN7Jf9fS3jh4aUvaep-blxnBR1CGq9eM"
GID_ROUTE_RULES = 58839224


@lru_cache(maxsize=1)
def load_route_rules() -> dict[str, list[dict[str, Any]]]:
    """
    Returns {market: [{route: str, keywords: [str, ...]}, ...]}.
    Mỗi rule: TẤT CẢ keywords trong cùng một cột (Giá trị 1, 2, ...) phải có trong tên tour.
    """
    import gspread

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    try:
        from google_auth import get_gspread_client
        gc = get_gspread_client()
    except Exception:
        path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(path, scopes=scopes)
        gc = gspread.authorize(creds)

    ws = gc.open_by_key(SHEET_ID).get_worksheet_by_id(GID_ROUTE_RULES)
    data = ws.get_all_values()
    rules: dict[str, list[dict[str, Any]]] = {}

    for row in data[2:]:
        if not row or not row[0].strip():
            continue
        market = row[0].strip()
        route = row[1].strip() if len(row) > 1 else market
        keywords_groups: list[list[str]] = []
        for cell in row[2:]:
            if cell and str(cell).strip():
                kws = [k.strip().lower() for k in str(cell).split(",") if k.strip()]
                if kws:
                    keywords_groups.append(kws)

        if not keywords_groups:
            continue

        if market not in rules:
            rules[market] = []
        for kws in keywords_groups:
            rules[market].append({"route": route, "keywords": kws})

    return rules


def resolve_tuyen_tour(
    thi_truong: str,
    ten_tour: str,
    lich_trinh: str = "",
    rules: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """First matching rule wins; default = thị trường."""
    if rules is None:
        rules = load_route_rules()

    market = (thi_truong or "").strip()
    combined = f"{ten_tour or ''} {lich_trinh or ''}".lower()
    route_found = market or "Khác"

    for rule in rules.get(market, []):
        if all(kw in combined for kw in rule["keywords"]):
            return rule["route"]

    return route_found
