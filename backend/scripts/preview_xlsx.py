"""Preview classification rules Excel file."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

XLSX = Path(r"c:\Users\thuon\Desktop\OTA\Quy_tắc_phân_loại_FINAL.xlsx")
OUT = Path(__file__).resolve().parents[2] / "tmp_xlsx_preview.json"


def main() -> None:
    df_map = pd.read_excel(XLSX, sheet_name=None)
    out: dict = {}
    for name, d in df_map.items():
        out[str(name)] = {
            "shape": list(d.shape),
            "columns": [str(c) for c in d.columns],
            "head": d.head(12).fillna("").astype(str).to_dict("records"),
        }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(OUT))
    print("sheets:", len(out))


if __name__ == "__main__":
    main()
