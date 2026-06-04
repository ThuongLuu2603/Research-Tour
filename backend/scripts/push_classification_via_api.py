"""Import quy tắc qua API hiện có (không cần endpoint mới)."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.import_classification_xlsx import parse_xlsx  # noqa: E402

XLSX = Path(r"c:\Users\thuon\Desktop\OTA\Quy_tắc_phân_loại_FINAL.xlsx")
BASE = "https://ota-research-platform.onrender.com"


def req(method: str, path: str, token: str, body: dict | None = None, timeout: int = 120):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def login() -> str:
    data = urllib.parse.urlencode({"username": "admin", "password": "admin123"}).encode()
    r = urllib.request.Request(f"{BASE}/api/auth/login", data=data, method="POST")
    r.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))["access_token"]


def main() -> None:
    market_order, rules = parse_xlsx(XLSX)
    token = login()

    existing = req("GET", "/api/admin/rules/route", token)
    deleted = 0
    for row in existing:
        req(
            "DELETE",
            f"/api/admin/rules/route/{row['id']}?auto_apply=false&push_sheet=false",
            token,
        )
        deleted += 1
        if deleted % 50 == 0:
            print(f"deleted {deleted}/{len(existing)}")

    created = 0
    for row in rules:
        req(
            "POST",
            "/api/admin/rules/route?auto_apply=false&push_sheet=false",
            token,
            {
                "thi_truong": row["thi_truong"],
                "tuyen_tour": row["tuyen_tour"],
                "keywords": row["keywords"],
                "sort_order": row["sort_order"],
                "active": True,
            },
        )
        created += 1
        if created % 50 == 0:
            print(f"created {created}/{len(rules)}")

    req("PUT", "/api/admin/rules/classify/market-order", token, {"markets": market_order})
    apply = req("POST", "/api/admin/rules/apply-classification-to-tours", token, timeout=300)

    result = {
        "deleted": deleted,
        "created": created,
        "market_order": market_order,
        "apply": apply,
    }
    out = BACKEND / "tmp_import_result.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
