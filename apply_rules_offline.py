#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_rules_offline.py — Áp dụng quy tắc phân loại tuyến tour trực tiếp vào Supabase
mà không đi qua API backend (tránh tốn Egress).

Chạy:
    python apply_rules_offline.py
    python apply_rules_offline.py --full-scan      # quét lại tất cả tour kể cả đã có rule_id
    python apply_rules_offline.py --dry-run        # chỉ in kết quả, không UPDATE
    python apply_rules_offline.py --batch 1000     # batch size (mặc định 500)

Yêu cầu: pip install psycopg2-binary
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.stdout.buffer.write(b"Thieu psycopg2. Chay: pip install psycopg2-binary\n")
    sys.exit(1)

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────────────────────────────────────────
# CẤU HÌNH — đổi DATABASE_URL nếu cần
# ─────────────────────────────────────────────────────────────────────────────
DATABASE_URL = (
    "postgresql://postgres.hjoqbknulolkxqqwjxno:Thuong%402603"
    "@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
)

# Chỉ áp dụng cho tour có nguon trong danh sách này
CANONICAL_NGUON = ("Main", "Vietravel")

# ─────────────────────────────────────────────────────────────────────────────
# fold_vi — bỏ dấu tiếng Việt (clone từ backend/text_fold.py)
# ─────────────────────────────────────────────────────────────────────────────
_WHITESPACE = re.compile(r"\s+")


def fold_vi(text: str) -> str:
    """
    Bỏ dấu + chữ thường + gộp khoảng trắng.
    'Châu Đà Nẵng' và 'chau da nang' → 'chau da nang'.
    'đ/Đ' xử lý riêng vì không decompose qua NFD.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text).strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    s = _WHITESPACE.sub(" ", s.lower())
    return s.strip()[:8000]


# ─────────────────────────────────────────────────────────────────────────────
# word-boundary match — tránh "my" khớp nhầm trong "myanmar"
# ─────────────────────────────────────────────────────────────────────────────
def _word_match(kw: str, text: str) -> bool:
    """
    Kiểm tra keyword xuất hiện như từ hoàn chỉnh trong text (đã fold_vi).
    'my' KHÔNG match trong 'myanmar', nhưng match trong 'du lich my'.
    """
    return bool(re.search(
        r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])",
        text,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Load rules từ DB
# ─────────────────────────────────────────────────────────────────────────────
def load_rules(conn) -> list[dict]:
    """
    Trả về list rules đã sort theo sort_order, mỗi rule là dict:
    {id, thi_truong, tuyen_tour, keywords: list[str (folded)]}
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, thi_truong, tuyen_tour, keywords
            FROM route_keyword_rules
            WHERE active = TRUE
            ORDER BY sort_order, id
            """
        )
        raw = cur.fetchall()

    rules = []
    for r in raw:
        kws_raw = [k.strip() for k in (r["keywords"] or "").split(",") if k.strip()]
        kws_folded = [fold_vi(k) for k in kws_raw if fold_vi(k)]
        if not kws_folded:
            continue
        rules.append({
            "id": r["id"],
            "thi_truong": (r["thi_truong"] or "").strip(),
            "tuyen_tour": (r["tuyen_tour"] or "").strip(),
            "kws": kws_folded,
        })
    return rules


# ─────────────────────────────────────────────────────────────────────────────
# Xây anchor index để tăng tốc (không cần thử hết 700+ rules mỗi tour)
# ─────────────────────────────────────────────────────────────────────────────
def build_anchor_index(rules: list[dict]) -> dict[str, list[int]]:
    """Map anchor_keyword → [rule_indices]."""
    idx: dict[str, list[int]] = {}
    for i, rule in enumerate(rules):
        anchor = max(rule["kws"], key=len)  # từ dài nhất = neo tìm kiếm
        idx.setdefault(anchor, []).append(i)
    return idx


# ─────────────────────────────────────────────────────────────────────────────
# Resolve một tour → (thi_truong, tuyen_tour, rule_id) hoặc None
# ─────────────────────────────────────────────────────────────────────────────
def resolve_tour(
    ten_tour: str,
    lich_trinh: str,
    rules: list[dict],
    anchor_idx: dict[str, list[int]],
) -> Optional[tuple[str, str, int]]:
    combined = fold_vi(f"{ten_tour or ''} {lich_trinh or ''}")
    if not combined:
        return None

    # Bước 1: tìm candidates từ anchor (fast substring)
    candidates: set[int] = set()
    for anchor, indices in anchor_idx.items():
        if anchor in combined:
            candidates.update(indices)
    if not candidates:
        return None

    # Bước 2: word-boundary check
    for i in sorted(candidates):
        rule = rules[i]
        if all(_word_match(kw, combined) for kw in rule["kws"]):
            return rule["thi_truong"], rule["tuyen_tour"], rule["id"]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main apply loop
# ─────────────────────────────────────────────────────────────────────────────
def run(
    db_url: str,
    full_scan: bool = False,
    dry_run: bool = False,
    batch_size: int = 500,
):
    print(f"{'[DRY-RUN] ' if dry_run else ''}Kết nối DB…")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    # Load rules
    print("Đang load route_keyword_rules…")
    rules = load_rules(conn)
    anchor_idx = build_anchor_index(rules)
    print(f"✓ {len(rules)} rules active, {len(anchor_idx)} anchor từ.")

    # Đếm tours cần xử lý
    with conn.cursor() as cur:
        if full_scan:
            cur.execute(
                "SELECT COUNT(*) FROM tours WHERE nguon = ANY(%s)",
                (list(CANONICAL_NGUON),),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) FROM tours
                WHERE nguon = ANY(%s)
                  AND (
                    classification_rule_id IS NULL
                    OR classified_at IS NULL
                    OR (updated_at IS NOT NULL AND updated_at > classified_at + interval '10 seconds')
                  )
                """,
                (list(CANONICAL_NGUON),),
            )
        total = cur.fetchone()[0]

    mode = "toàn bộ (full-scan)" if full_scan else "chưa classify / có thay đổi"
    print(f"Cần xử lý: {total} tours [{mode}]\n")
    if total == 0:
        print("✓ Không có tour nào cần cập nhật.")
        conn.close()
        return

    # Xử lý theo batch
    processed = 0
    updated = 0
    cleared = 0
    start_time = time.time()
    last_id = 0
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC cho DB

    while True:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if full_scan:
                cur.execute(
                    """
                    SELECT id, ten_tour, lich_trinh,
                           thi_truong, tuyen_tour, classification_rule_id
                    FROM tours
                    WHERE nguon = ANY(%s) AND id > %s
                    ORDER BY id
                    LIMIT %s
                    """,
                    (list(CANONICAL_NGUON), last_id, batch_size),
                )
            else:
                cur.execute(
                    """
                    SELECT id, ten_tour, lich_trinh,
                           thi_truong, tuyen_tour, classification_rule_id
                    FROM tours
                    WHERE nguon = ANY(%s)
                      AND id > %s
                      AND (
                        classification_rule_id IS NULL
                        OR classified_at IS NULL
                        OR (updated_at IS NOT NULL AND updated_at > classified_at + interval '10 seconds')
                      )
                    ORDER BY id
                    LIMIT %s
                    """,
                    (list(CANONICAL_NGUON), last_id, batch_size),
                )
            batch = cur.fetchall()

        if not batch:
            break

        # Tính kết quả cho từng tour
        updates: list[tuple] = []   # (thi_truong, tuyen_tour, rule_id, now, id)
        clears: list[int] = []      # id cần xóa (không match rule nào)

        for row in batch:
            tour_id = row["id"]
            result = resolve_tour(
                row["ten_tour"] or "",
                row["lich_trinh"] or "",
                rules,
                anchor_idx,
            )

            if result:
                tt, tuyen, rule_id = result
                # Chỉ update nếu thực sự thay đổi
                if (
                    row["thi_truong"] != tt
                    or row["tuyen_tour"] != tuyen
                    or row["classification_rule_id"] != rule_id
                ):
                    updates.append((tt, tuyen, rule_id, now_utc, tour_id))
            else:
                # Tour không khớp rule nào — chỉ đặt classified_at để không quét lại
                clears.append(tour_id)

        # Thực hiện UPDATE
        if not dry_run:
            with conn.cursor() as cur:
                if updates:
                    psycopg2.extras.execute_batch(
                        cur,
                        """
                        UPDATE tours
                        SET thi_truong = %s,
                            tuyen_tour  = %s,
                            classification_rule_id = %s,
                            classified_at = %s
                        WHERE id = %s
                        """,
                        updates,
                        page_size=200,
                    )
                if clears:
                    psycopg2.extras.execute_batch(
                        cur,
                        "UPDATE tours SET classified_at = %s WHERE id = %s",
                        [(now_utc, tid) for tid in clears],
                        page_size=200,
                    )
            conn.commit()

        processed += len(batch)
        updated += len(updates)
        cleared += len(clears)
        last_id = batch[-1]["id"]

        # Progress
        elapsed = time.time() - start_time
        pct = processed * 100 // max(total, 1)
        speed = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / speed if speed > 0 else 0
        print(
            f"  [{pct:3d}%] {processed:5d}/{total} tour  |  "
            f"updated={updated}  skipped={cleared}  |  "
            f"{speed:.0f} t/s  ETA={eta:.0f}s",
            end="\r",
            flush=True,
        )

    print()  # newline sau \r
    elapsed = time.time() - start_time

    if dry_run:
        print(f"\n[DRY-RUN] Sẽ update {updated} tours, skip {cleared} tours")
    else:
        print(f"\n✅ Hoàn thành trong {elapsed:.1f}s")
        print(f"   Tours cập nhật (rule mới/đổi): {updated}")
        print(f"   Tours đánh dấu classified_at:   {cleared}")
        print(f"   Tổng xử lý:                     {processed}")

    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Áp dụng quy tắc phân loại tuyến tour vào Supabase (offline, không qua API)"
    )
    parser.add_argument(
        "--db-url",
        default=DATABASE_URL,
        help="PostgreSQL connection URL (mặc định: dùng URL đã cấu hình trong script)",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Quét lại TẤT CẢ tours (kể cả đã có rule_id). Mặc định chỉ quét tours chưa classify.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Không UPDATE, chỉ đếm và in kết quả.",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=500,
        help="Số tour xử lý mỗi lần truy vấn (mặc định: 500)",
    )
    args = parser.parse_args()

    try:
        run(
            db_url=args.db_url,
            full_scan=args.full_scan,
            dry_run=args.dry_run,
            batch_size=args.batch,
        )
    except KeyboardInterrupt:
        print("\n⚠ Dừng bởi người dùng (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Lỗi: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
