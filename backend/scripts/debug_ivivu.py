"""Chẩn đoán cấu trúc ivivu.com/du-lich/ để viết scraper.

Chạy TRÊN VPS (IP thật mà scraper sẽ dùng) để biết:
  1. Cloudflare có chặn IP VPS không (403) — quyết định cần proxy hay không.
  2. Tour data nằm ở JSON state nhúng (vd "search-tour-destination") hay HTML cards.
  3. Mẫu cấu trúc để viết parser.

Usage:
    cd /var/www/ota/backend && set -a && source .env && set +a
    venv/bin/python scripts/debug_ivivu.py
"""
from __future__ import annotations

import re
import sys

import requests

URL = "https://www.ivivu.com/du-lich/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
}


def main() -> int:
    try:
        r = requests.get(URL, headers=HEADERS, timeout=30)
    except Exception as e:  # noqa: BLE001
        print("REQUEST FAILED:", e)
        return 1
    html = r.text
    print(f"STATUS {r.status_code}  len={len(html)}  server={r.headers.get('server')}")
    low = html.lower()

    # 1. Cloudflare / bot challenge?
    cf = any(m in low for m in ("cf-chl", "cloudflare", "checking your browser", "challenge-platform", "_cf_chl"))
    print(f"Cloudflare/bot-challenge dau hieu: {cf}")
    if r.status_code != 200 or len(html) < 5000:
        print("  -> Co the bi chan / trang rong. Snippet 1000 ky tu dau:")
        print(html[:1000])
        return 0

    # 2. JSON state markers
    print("\n--- JSON STATE MARKERS ---")
    for m in ("search-tour-destination", "__NUXT__", "window.__INITIAL", "__NEXT_DATA__",
              "ng-state", "ngState", "tourList", "listTour", "application/json", "application/ld+json"):
        print(f"  {m!r}: {m in html}")

    # 3. Cac block <script type=...json...>
    print("\n--- SCRIPT JSON BLOCKS ---")
    blocks = re.findall(r'<script[^>]*type="application/(?:json|ld\+json)"[^>]*>(.*?)</script>',
                        html, re.S | re.I)
    print(f"So block JSON: {len(blocks)}")
    for i, b in enumerate(blocks[:6]):
        b = b.strip()
        print(f"  [{i}] len={len(b)} head={b[:140]!r}")

    # 4. ng-state (Angular SSR transfer state)
    ng = re.findall(r'id="([^"]*state[^"]*)"', html, re.I)
    if ng:
        print("\n--- id chua 'state' ---", ng[:8])

    # 5. Gia xuat hien
    print("\n--- PRICE-LIKE ---")
    prices = re.findall(r"([\d][\d.]{4,})\s*đ", html)
    print(f"So gia: {len(prices)} | mau: {prices[:8]}")

    # 6. Snippet quanh tour dau tien (tim 'tour' link)
    print("\n--- SNIPPET quanh link tour dau tien ---")
    m = re.search(r'href="(/[^"]*tour[^"]*)"', html, re.I)
    if m:
        pos = m.start()
        print(html[max(0, pos - 200):pos + 400])
    else:
        print("(khong tim thay href chua 'tour')")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
