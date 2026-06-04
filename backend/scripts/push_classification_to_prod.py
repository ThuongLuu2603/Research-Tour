"""Parse Excel và gửi quy tắc lên production API (ghi thẳng Supabase qua server)."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.import_classification_xlsx import parse_xlsx  # noqa: E402

XLSX = Path(r"c:\Users\thuon\Desktop\OTA\Quy_tắc_phân_loại_FINAL.xlsx")
BASE = "https://ota-research-platform.onrender.com"
LOGIN = f"{BASE}/api/auth/login"
REPLACE = f"{BASE}/api/admin/rules/route/replace-all"


def login(username: str = "admin", password: str = "admin123") -> str:
    data = f"username={username}&password={password}".encode()
    req = urllib.request.Request(LOGIN, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["access_token"]


def replace_rules(token: str, market_order: list[str], rules: list[dict], auto_apply: bool = True) -> dict:
    body = json.dumps(
        {"rules": rules, "market_order": market_order, "auto_apply": auto_apply},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(REPLACE, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    market_order, rules = parse_xlsx(XLSX)
    out = BACKEND / "tmp_rules_payload.json"
    out.write_text(
        json.dumps({"market_order": market_order, "rules": rules}, ensure_ascii=False),
        encoding="utf-8",
    )
    token = login()
    try:
        result = replace_rules(token, market_order, rules, auto_apply=True)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {e.code}: {detail}") from e
    result_path = BACKEND / "tmp_import_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(result_path))


if __name__ == "__main__":
    main()
