"""Import quy tắc phân loại từ file Excel vào Supabase/Postgres."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

COL_TT, COL_NUM, COL_ROUTE, COL_KW = 0, 1, 2, 3


def parse_keywords(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"\(\s*\d+\s*AND\s*\)\s*$", "", s, flags=re.I).strip()
    if re.search(r"\s+và\s+", s, flags=re.I):
        parts = re.split(r"\s+và\s+", s, flags=re.I)
        parts = [p.strip().lower() for p in parts if p.strip()]
        return ", ".join(parts)
    return s.lower()


def parse_xlsx(path: Path) -> tuple[list[str], list[dict]]:
    df = pd.read_excel(path, sheet_name=0, header=None)
    tt_to_market: dict[str, str] = {}
    market_order: list[str] = []
    rules: list[dict] = []
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
        if not c0.isdigit() or not c1.isdigit() or not c2 or not c3:
            continue

        market = tt_to_market.get(c0, "")
        if not market:
            continue
        keywords = parse_keywords(c3)
        if not keywords:
            continue
        rules.append(
            {
                "sort_order": sort_order,
                "thi_truong": market,
                "tuyen_tour": c2,
                "keywords": keywords,
            }
        )
        sort_order += 1

    return market_order, rules


def import_to_db(xlsx: Path, *, dry_run: bool = False) -> dict:
    market_order, rules = parse_xlsx(xlsx)
    if not rules:
        raise RuntimeError("Không parse được quy tắc nào từ file Excel")

    if dry_run:
        return {
            "dry_run": True,
            "rule_count": len(rules),
            "market_order": market_order,
            "sample": rules[:5],
        }

    from classification_rules_import import replace_route_rules
    from database import SessionLocal

    db = SessionLocal()
    try:
        return replace_route_rules(db, rules, market_order)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import quy tắc phân loại từ Excel vào DB")
    parser.add_argument(
        "xlsx",
        nargs="?",
        default=r"c:\Users\thuon\Desktop\OTA\Quy_tắc_phân_loại_FINAL.xlsx",
        help="Đường dẫn file Excel",
    )
    parser.add_argument("--dry-run", action="store_true", help="Chỉ parse, không ghi DB")
    args = parser.parse_args()

    path = Path(args.xlsx)
    if not path.is_file():
        raise SystemExit(f"Không tìm thấy file: {path}")

    result = import_to_db(path, dry_run=args.dry_run)
    out_path = BACKEND / "tmp_import_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
