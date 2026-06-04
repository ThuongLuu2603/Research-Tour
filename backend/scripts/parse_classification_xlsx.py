"""Parse classification rules xlsx structure."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

XLSX = Path(r"c:\Users\thuon\Desktop\OTA\Quy_tắc_phân_loại_FINAL.xlsx")
OUT = Path(__file__).resolve().parents[2] / "tmp_xlsx_parsed.json"

COL_TT = 0
COL_NUM = 1
COL_ROUTE = 2
COL_KW = 3


def parse_keywords(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"\(\s*\d+\s*AND\s*\)\s*$", "", s, flags=re.I).strip()
    if " và " in s.lower():
        parts = re.split(r"\s+và\s+", s, flags=re.I)
        parts = [p.strip().lower() for p in parts if p.strip()]
        return ", ".join(parts)
    return s.lower()


def parse_xlsx(path: Path) -> dict:
    df = pd.read_excel(path, sheet_name=0, header=None)
    tt_to_market: dict[str, str] = {}
    market_order: list[str] = []
    rules: list[dict] = []
    current_market = ""
    sort_order = 0

    for _, row in df.iterrows():
        c0 = str(row.iloc[COL_TT]).strip() if pd.notna(row.iloc[COL_TT]) else ""
        c1 = str(row.iloc[COL_NUM]).strip() if pd.notna(row.iloc[COL_NUM]) else ""
        c2 = str(row.iloc[COL_ROUTE]).strip() if pd.notna(row.iloc[COL_ROUTE]) else ""
        c3 = str(row.iloc[COL_KW]).strip() if pd.notna(row.iloc[COL_KW]) else ""

        m = re.match(r"^(\d+)\.\s*(.+?)(?:\s*\(\d+\s*dòng\))?\s*$", c0, re.I)
        if m and not c1 and not c2:
            tt = m.group(1)
            market = m.group(2).strip()
            tt_to_market[tt] = market
            if market not in market_order:
                market_order.append(market)
            continue

        if c1 == "#" and c2 == "Tuyến":
            continue

        if not c0 or not c2 or not c3:
            continue
        if not c0.isdigit() or not c1.isdigit():
            continue

        tt = c0
        market = tt_to_market.get(tt, current_market)
        if not market:
            continue
        current_market = market
        keywords = parse_keywords(c3)
        if not keywords:
            continue
        rules.append(
            {
                "sort_order": sort_order,
                "thi_truong": market,
                "tuyen_tour": c2,
                "keywords": keywords,
                "raw_keywords": c3,
            }
        )
        sort_order += 1

    return {
        "tt_to_market": tt_to_market,
        "market_order": market_order,
        "rules": rules,
        "rule_count": len(rules),
    }


def main() -> None:
    parsed = parse_xlsx(XLSX)
    OUT.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUT)
    print("rules", parsed["rule_count"])
    print("markets", parsed["market_order"])


if __name__ == "__main__":
    main()
