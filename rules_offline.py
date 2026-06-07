#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rules_offline.py — Quản lý quy tắc phân loại (route_keyword_rules) offline.
Kết nối thẳng Supabase PostgreSQL — không tốn Egress REST.

Cách dùng:
  # Xem rules
  python rules_offline.py --list
  python rules_offline.py --list --market "Việt Nam"
  python rules_offline.py --list --market "Thái Lan" --route "Bangkok - Pattaya"
  python rules_offline.py --list --only-priority      # chỉ xem rules ưu tiên

  # Preview: keyword này sẽ match bao nhiêu tour?
  python rules_offline.py --preview --keyword "koh samui"
  python rules_offline.py --preview --keyword "đà lạt, thác datanla"   # AND rule

  # Thêm rule mới
  python rules_offline.py --add --market "Thái Lan" --route "Koh Samui" --keyword "koh samui"
  python rules_offline.py --add --market "Việt Nam" --route "Miền Trung - Tây Nguyên" --keyword "đà lạt, thác datanla"

  # Thêm rule ƯU TIÊN (kiểm tra trước tất cả, nếu khớp dừng ngay)
  python rules_offline.py --add --market "Khác" --route "Không xác định" --keyword "tour học sinh" --priority --yes
  python rules_offline.py --add --market "Khác" --route "Không xác định" --keyword "teambuilding" --priority --yes
  python rules_offline.py --add --market "Khác" --route "Combo" --keyword "combo" --priority --yes

  # Bật/tắt ưu tiên cho rule có sẵn
  python rules_offline.py --set-priority --id 1234         # bật
  python rules_offline.py --set-priority --id 1234 --off   # tắt

  # Thêm nhiều rules từ file
  python rules_offline.py --import-file rules_to_add.txt

  # Xóa / bật-tắt rule
  python rules_offline.py --delete --id 1234
  python rules_offline.py --toggle --id 1234

Lưu ý về PRIORITY:
  - Rule priority=True được kiểm tra TRƯỚC TẤT CẢ rule khác
  - Nếu tour khớp 1 rule priority → dừng ngay, không check thêm
  - Dùng cho: "tour học sinh", "teambuilding", "combo", "khuyến mãi đặc biệt"
  - Trong file import, thêm dấu ! ở đầu tuyến: "Khác | !Không xác định | tour học sinh"

Lưu ý chung:
  - Keywords trong 1 rule cách nhau bằng dấu phẩy = AND (tour phải có TẤT CẢ)
  - Matching dùng word-boundary: "my" KHÔNG match "myanmar"
  - KHÔNG add tuyến chung chung trùng tên thị trường
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    sys.stdout.buffer.write(b"Thieu psycopg2. Chay: pip install psycopg2-binary\n")
    sys.exit(1)

# Fix UTF-8 stdout Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ─── Cấu hình DB ───────────────────────────────────────────────────────────────
# Production đã migrate sang CockroachDB Cloud (06/2026). KHÔNG hard-code URL trong file
# (tránh lỡ commit secret). Lấy theo thứ tự ưu tiên:
#   1) --db-url <URL> trên CLI (override mọi thứ)
#   2) DATABASE_URL env var
#   3) DATABASE_POOLER_URL env var (Render Supabase legacy, vẫn fallback nếu muốn dùng)
# Nếu không có nguồn nào → in hướng dẫn và exit để khỏi import lầm vào DB cũ.


def _resolve_db_url(cli_url: str | None) -> str:
    url = (
        cli_url
        or os.environ.get("DATABASE_URL")
        or os.environ.get("DATABASE_POOLER_URL")
        or ""
    ).strip()
    if not url:
        sys.stderr.write(
            "❌ Chưa có DB URL.\n"
            "   Cách 1: set env var trước khi chạy\n"
            "     Windows PowerShell:  $env:DATABASE_URL = 'postgresql://...cockroachlabs.cloud:26257/...'\n"
            "     macOS/Linux:        export DATABASE_URL='postgresql://...cockroachlabs.cloud:26257/...'\n"
            "   Cách 2: truyền qua CLI\n"
            "     python rules_offline.py --db-url 'postgresql://...' --list\n"
            "\n"
            "   Lấy URL từ: Render dashboard → service → Environment → DATABASE_URL\n"
            "   hoặc CockroachDB Cloud → Cluster → Connect → 'sql' driver.\n"
        )
        sys.exit(2)
    # Cảnh báo sớm nếu vẫn trỏ Supabase mà production đã chuyển sang CockroachDB
    if "cockroachlabs.cloud" not in url and "supabase" in url.lower():
        sys.stderr.write(
            "⚠️  URL đang trỏ Supabase. App production hiện chạy CockroachDB Cloud — "
            "import vào Supabase sẽ KHÔNG hiện trên UI Render.\n"
            "    Bấm Ctrl+C để hủy, hoặc Enter để tiếp tục.\n"
        )
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            sys.exit(2)
    return url


# Lazy — chỉ tính khi parse args xong.
DATABASE_URL: str = ""

CANONICAL_NGUON = ("Main", "Vietravel")

# ─── fold_vi + word-boundary (clone từ backend) ────────────────────────────────
_WS = re.compile(r"\s+")


def fold_vi(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text).strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    return _WS.sub(" ", s.lower()).strip()[:8000]


def word_match(kw: str, text: str) -> bool:
    """'my' KHÔNG match trong 'myanmar', match trong 'du lich my'."""
    return bool(re.search(
        r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])",
        text,
    ))


def matches_rule(keywords_str: str, ten_tour: str, lich_trinh: str) -> bool:
    """Kiểm tra 1 rule (AND) có khớp tour không."""
    text = fold_vi(f"{ten_tour or ''} {lich_trinh or ''}")
    kws = [fold_vi(k) for k in keywords_str.split(",") if k.strip()]
    return bool(kws) and all(word_match(k, text) for k in kws)


# ─── Kết nối DB ────────────────────────────────────────────────────────────────
def connect(db_url: str = DATABASE_URL):
    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    return conn


def ensure_priority_column(conn) -> None:
    """Tự động thêm cột priority nếu chưa có (migration an toàn)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name='route_keyword_rules' AND column_name='priority'
        """)
        if cur.fetchone() is None:
            cur.execute(
                "ALTER TABLE route_keyword_rules ADD COLUMN priority boolean NOT NULL DEFAULT false"
            )
            conn.commit()
            print("  ✓ Đã thêm cột 'priority' vào route_keyword_rules")


# ─── COMMANDS ──────────────────────────────────────────────────────────────────

def cmd_list(conn, market: str = "", route: str = "", only_priority: bool = False) -> None:
    """Hiển thị danh sách rules, lọc theo market/route nếu có."""
    sql = """
        SELECT id, thi_truong, tuyen_tour, keywords, active,
               COALESCE(priority, false) as priority, sort_order
        FROM route_keyword_rules
        WHERE 1=1
    """
    params = []
    if market:
        sql += " AND LOWER(thi_truong) LIKE LOWER(%s)"
        params.append(f"%{market}%")
    if route:
        sql += " AND LOWER(tuyen_tour) LIKE LOWER(%s)"
        params.append(f"%{route}%")
    if only_priority:
        sql += " AND priority = true"
    sql += " ORDER BY priority DESC, thi_truong, tuyen_tour, sort_order, id"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        print("  (Không có rule nào phù hợp)")
        return

    print(f"\n  {'ID':>6}  {'P':>1}  {'Thị trường':<18} {'Tuyến tour':<30} {'Keywords':<40} {'On':>2}  {'Sort':>5}")
    print("  " + "─" * 108)
    prev_prio = None
    prev_market = ""
    for rid, tt, tuyen, kw, active, prio, sort in rows:
        # Gạch phân cách khi chuyển từ priority → thường
        if prev_prio is True and not prio:
            print("  " + "╌" * 108)
        if tt != prev_market and prev_market:
            print()
        prev_prio = prio
        prev_market = tt
        prio_mark = "★" if prio else " "
        status = "✓" if active else "✗"
        kw_disp = (kw or "")[:38]
        print(f"  {rid:>6}  {prio_mark}  {(tt or ''):<18} {(tuyen or ''):<30} {kw_disp:<40} {status:>2}  {sort:>5}")

    n_prio = sum(1 for r in rows if r[5])
    print(f"\n  Tổng: {len(rows)} rules  (★ {n_prio} ưu tiên)")
    if n_prio:
        print("  Ghi chú: ★ = priority — luôn kiểm tra TRƯỚC, nếu khớp → dừng ngay")


def cmd_preview(conn, keywords_str: str, market: str = "", route: str = "") -> None:
    """Preview keyword sẽ match bao nhiêu tour (trước khi thêm rule)."""
    kws_raw = [k.strip() for k in keywords_str.split(",") if k.strip()]
    if not kws_raw:
        print("  Keyword trống.")
        return

    kws_folded = [fold_vi(k) for k in kws_raw]
    print(f"\n  Preview keyword: {keywords_str!r}")
    print(f"  Sau fold_vi:     {kws_folded}")
    print(f"  Logic:           {'AND'.join(repr(k) for k in kws_folded)} phải xuất hiện trong tên/lịch trình")
    print()

    # Đếm và lấy sample tours matching
    sql = """
        SELECT id, ten_tour, lich_trinh, thi_truong, tuyen_tour, cong_ty
        FROM tours
        WHERE nguon = ANY(%s)
    """
    params: list = [list(CANONICAL_NGUON)]
    if market:
        sql += " AND thi_truong ILIKE %s"
        params.append(f"%{market}%")
    if route:
        sql += " AND tuyen_tour ILIKE %s"
        params.append(f"%{route}%")
    sql += " ORDER BY id"

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        all_tours = cur.fetchall()

    matched = [t for t in all_tours if matches_rule(keywords_str, t["ten_tour"], t["lich_trinh"])]

    pct = len(matched) * 100 // max(len(all_tours), 1)
    print(f"  Kết quả: {len(matched)}/{len(all_tours)} tours phù hợp ({pct}%)")

    if matched:
        print(f"\n  Sample (tối đa 10 tour đầu):")
        for t in matched[:10]:
            tt = (t["thi_truong"] or "")[:15]
            tuyen = (t["tuyen_tour"] or "")[:20]
            ten = (t["ten_tour"] or "")[:60]
            co = (t["cong_ty"] or "")[:15]
            print(f"    [{t['id']:6d}] {tt:<15} | {tuyen:<20} | {ten} ({co})")
    else:
        print("  Không có tour nào phù hợp với keyword này.")

    # Cảnh báo nếu keyword quá rộng
    if len(matched) > 500:
        print(f"\n  ⚠  Cảnh báo: {len(matched)} tours là khá nhiều. Cân nhắc thêm keyword phụ (AND).")


def _get_max_sort_order(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(sort_order), 584) FROM route_keyword_rules")
        return cur.fetchone()[0]


def _rule_exists(conn, market: str, route: str, keyword: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM route_keyword_rules WHERE thi_truong=%s AND tuyen_tour=%s AND keywords=%s",
            (market, route, keyword),
        )
        return cur.fetchone()[0] > 0


def _validate_route_not_generic(market: str, route: str) -> bool:
    """Trả False nếu tuyến bị coi là 'chung chung' trùng thị trường."""
    mkt_fold = fold_vi(market)
    rt_fold = fold_vi(route)
    # So sánh tuyến == thị trường (bỏ dấu)
    if mkt_fold == rt_fold:
        return False
    # Tuyến chỉ là 1 từ và khớp 100% với thị trường
    if rt_fold in mkt_fold and len(rt_fold.split()) <= 2 and len(mkt_fold.split()) <= 2:
        return False
    return True


def cmd_add(
    conn,
    market: str,
    route: str,
    keyword: str,
    sort_order: Optional[int] = None,
    priority: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> bool:
    """Thêm 1 rule mới."""
    market = market.strip()
    route = route.strip()
    keyword = keyword.strip()

    if not market or not route or not keyword:
        print("  Lỗi: --market, --route, --keyword không được để trống.")
        return False

    # Validate tuyến không chung chung
    if not _validate_route_not_generic(market, route):
        print(f"  ✗ Từ chối: Tuyến '{route}' bị coi là chung chung trùng thị trường '{market}'.")
        print(f"    Hãy đặt tên tuyến cụ thể hơn (vd: 'Bangkok - Pattaya' thay vì 'Thái Lan').")
        return False

    # Kiểm tra đã tồn tại
    if _rule_exists(conn, market, route, keyword):
        print(f"  ℹ  Rule đã tồn tại: {market} | {route} | {keyword!r}")
        return False

    # Preview match
    print()
    cmd_preview(conn, keyword, market="", route="")

    prio_label = " [★ PRIORITY]" if priority else ""

    if dry_run:
        print(f"\n  [DRY-RUN] Sẽ thêm rule{prio_label}: {market} | {route} | {keyword!r}")
        return True

    # Xác nhận
    if not yes:
        ans = input(f"\n  Thêm rule{prio_label} [{market}] | [{route}] | [{keyword!r}]? (y/N) ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Hủy.")
            return False

    so = sort_order if sort_order is not None else _get_max_sort_order(conn) + 1
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO route_keyword_rules (thi_truong, tuyen_tour, keywords, active, priority, sort_order, updated_at)
               VALUES (%s, %s, %s, true, %s, %s, %s) RETURNING id""",
            (market, route, keyword, priority, so, now),
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    prio_mark = " ★" if priority else ""
    print(f"\n  ✓ Đã thêm rule id={new_id}{prio_mark}: [{market}] | [{route}] | [{keyword!r}] (sort={so})")
    if priority:
        print("    → Rule này sẽ được kiểm tra TRƯỚC TẤT CẢ, nếu khớp → dừng ngay")
    return True


def cmd_delete(conn, rule_id: int, yes: bool = False) -> bool:
    """Xóa rule theo ID."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM route_keyword_rules WHERE id=%s", (rule_id,))
        rule = cur.fetchone()

    if not rule:
        print(f"  ✗ Không tìm thấy rule id={rule_id}")
        return False

    print(f"  Rule: id={rule['id']} | {rule['thi_truong']} | {rule['tuyen_tour']} | {rule['keywords']!r}")

    if not yes:
        ans = input("  Xóa rule này? (y/N) ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Hủy.")
            return False

    with conn.cursor() as cur:
        cur.execute("DELETE FROM route_keyword_rules WHERE id=%s", (rule_id,))
    conn.commit()
    print(f"  ✓ Đã xóa rule id={rule_id}")
    return True


def cmd_set_priority(conn, rule_id: int, off: bool = False) -> bool:
    """Bật/tắt priority cho rule theo ID."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(priority,false), thi_truong, tuyen_tour, keywords FROM route_keyword_rules WHERE id=%s",
            (rule_id,),
        )
        row = cur.fetchone()

    if not row:
        print(f"  ✗ Không tìm thấy rule id={rule_id}")
        return False

    cur_prio, tt, tuyen, kw = row
    new_prio = False if off else True

    if cur_prio == new_prio:
        status = "ƯU TIÊN" if new_prio else "thường"
        print(f"  ℹ  Rule id={rule_id} đã ở trạng thái {status} rồi, không thay đổi.")
        return False

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE route_keyword_rules SET priority=%s, updated_at=%s WHERE id=%s",
            (new_prio, datetime.now(timezone.utc).replace(tzinfo=None), rule_id),
        )
    conn.commit()

    if new_prio:
        print(f"  ★ Rule id={rule_id} [{tt} | {tuyen} | {kw!r}] → ƯU TIÊN (kiểm tra trước tất cả)")
    else:
        print(f"  ○ Rule id={rule_id} [{tt} | {tuyen} | {kw!r}] → thường (đã tắt ưu tiên)")
    return True


def cmd_toggle(conn, rule_id: int) -> bool:
    """Bật/tắt rule (active flag)."""
    with conn.cursor() as cur:
        cur.execute("SELECT active, thi_truong, tuyen_tour, keywords FROM route_keyword_rules WHERE id=%s", (rule_id,))
        row = cur.fetchone()

    if not row:
        print(f"  ✗ Không tìm thấy rule id={rule_id}")
        return False

    active, tt, tuyen, kw = row
    new_active = not active
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE route_keyword_rules SET active=%s, updated_at=%s WHERE id=%s",
            (new_active, datetime.now(timezone.utc).replace(tzinfo=None), rule_id),
        )
    conn.commit()
    status = "BẬT" if new_active else "TẮT"
    print(f"  ✓ Rule id={rule_id} [{tt} | {tuyen} | {kw!r}] → {status}")
    return True


def cmd_import_file(
    conn,
    filepath: str,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """
    Import rules từ file text. Mỗi dòng có định dạng:
        thi_truong | tuyen_tour | keyword
    Hoặc CSV:
        thi_truong,tuyen_tour,keyword
    Dòng bắt đầu bằng # là comment.

    Ví dụ rules_to_add.txt:
        Thái Lan | Koh Samui | koh samui
        Thái Lan | Koh Samui | ko samui
        Nhật Bản | Kyushu    | nagasaki, hiroshima
        # Comment này bị bỏ qua
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"  ✗ Không tìm thấy file: {filepath}")
        return

    parsed = []
    errors = []
    for i, line in enumerate(lines, 1):
        # Bỏ comment inline (phần sau #)
        if "#" in line:
            line = line[:line.index("#")]
        line = line.strip()
        if not line:
            continue
        # Thử phân tách bằng | hoặc ,
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
        else:
            parts = [p.strip() for p in line.split(",", 2)]

        if len(parts) < 3:
            errors.append(f"  Dòng {i}: Không đủ 3 phần — {line!r}")
            continue
        market, route, keyword = parts[0], parts[1], parts[2]
        if not market or not route or not keyword:
            errors.append(f"  Dòng {i}: Có trường trống — {line!r}")
            continue
        # Dấu ! ở đầu tuyến = priority rule
        is_priority = route.startswith("!")
        if is_priority:
            route = route[1:].strip()
        parsed.append((market, route, keyword, is_priority))

    if errors:
        print("  Lỗi parse:")
        for e in errors:
            print(e)

    if not parsed:
        print("  Không có rule hợp lệ nào trong file.")
        return

    print(f"\n  File: {filepath}")
    print(f"  Tổng dòng hợp lệ: {len(parsed)}")
    print()

    added = skipped_dup = skipped_generic = skipped_err = 0
    so_base = _get_max_sort_order(conn)

    for market, route, keyword, is_priority in parsed:
        # Validate tuyến không chung chung
        if not _validate_route_not_generic(market, route):
            print(f"  ✗ SKIP (tuyến chung): {market} | {route} | {keyword!r}")
            skipped_generic += 1
            continue

        # Kiểm tra duplicate
        if _rule_exists(conn, market, route, keyword):
            print(f"  ℹ  DUP: {market} | {route} | {keyword!r}")
            skipped_dup += 1
            continue

        so_base += 1
        prio_mark = " ★" if is_priority else ""
        if dry_run:
            print(f"  + DRY{prio_mark}: {market} | {route} | {keyword!r} (sort={so_base})")
            added += 1
            continue

        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO route_keyword_rules (thi_truong, tuyen_tour, keywords, active, priority, sort_order, updated_at)
                       VALUES (%s, %s, %s, true, %s, %s, %s) RETURNING id""",
                    (market, route, keyword, is_priority, so_base, now),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
            print(f"  ✓{prio_mark} id={new_id:5d} | {market:<20} | {route:<30} | {keyword!r}")
            added += 1
        except Exception as e:
            conn.rollback()
            print(f"  ✗ Lỗi: {market} | {route} | {keyword!r} — {e}")
            skipped_err += 1

    print()
    print(f"  Kết quả: +{added} thêm  |  {skipped_dup} đã tồn tại  |  {skipped_generic} tuyến chung  |  {skipped_err} lỗi")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM route_keyword_rules")
        total = cur.fetchone()[0]
    print(f"  Tổng rules hiện tại: {total}")


# ─── CLI ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Quản lý quy tắc phân loại tuyến tour (offline, không qua API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python rules_offline.py --list
  python rules_offline.py --list --market "Thái Lan"
  python rules_offline.py --preview --keyword "koh samui"
  python rules_offline.py --preview --keyword "đà lạt, thác datanla"
  python rules_offline.py --add --market "Thái Lan" --route "Koh Samui" --keyword "koh samui"
  python rules_offline.py --add --market "Thái Lan" --route "Koh Samui" --keyword "koh samui" --yes
  python rules_offline.py --delete --id 1234
  python rules_offline.py --toggle --id 1234
  python rules_offline.py --import-file rules_to_add.txt
  python rules_offline.py --import-file rules_to_add.txt --dry-run

Format file import (rules_to_add.txt):
  # Dòng bắt đầu bằng # là comment
  Thái Lan | Koh Samui     | koh samui
  Thái Lan | Koh Samui     | ko samui
  Nhật Bản | Kyushu        | nagasaki, hiroshima    # AND rule
  Việt Nam | Tây Bắc       | mù cang chải
        """,
    )

    # Action (chọn 1)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="Xem danh sách rules")
    action.add_argument("--preview", action="store_true", help="Preview keyword match bao nhiêu tour")
    action.add_argument("--add", action="store_true", help="Thêm rule mới")
    action.add_argument("--delete", action="store_true", help="Xóa rule theo --id")
    action.add_argument("--toggle", action="store_true", help="Bật/tắt active theo --id")
    action.add_argument("--set-priority", action="store_true", help="Bật/tắt ưu tiên theo --id (dùng --off để tắt)")
    action.add_argument("--import-file", metavar="FILE", help="Import nhiều rules từ file text")

    # Params
    parser.add_argument("--market", default="", help="Thị trường (vd: 'Thái Lan')")
    parser.add_argument("--route", default="", help="Tuyến tour (vd: 'Bangkok - Pattaya')")
    parser.add_argument("--keyword", default="", help="Keyword (dùng dấu phẩy cho AND: 'kw1, kw2')")
    parser.add_argument("--id", type=int, help="ID của rule cần xóa/toggle/set-priority")
    parser.add_argument("--sort", type=int, default=None, help="sort_order cho rule mới (mặc định: max+1)")
    parser.add_argument("--priority", action="store_true", help="Đánh dấu rule mới là ưu tiên (★)")
    parser.add_argument("--off", action="store_true", help="Dùng với --set-priority để TẮT ưu tiên")
    parser.add_argument("--only-priority", action="store_true", help="Dùng với --list: chỉ hiện rules ưu tiên")
    parser.add_argument("--dry-run", action="store_true", help="Không ghi DB, chỉ xem kết quả")
    parser.add_argument("--yes", "-y", action="store_true", help="Bỏ qua bước xác nhận")
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL (mặc định lấy từ env var DATABASE_URL hoặc DATABASE_POOLER_URL)",
    )

    args = parser.parse_args()

    # Resolve DB URL: --db-url > DATABASE_URL env > DATABASE_POOLER_URL env > error.
    # Cảnh báo nếu URL trỏ Supabase (production đã sang CockroachDB).
    db_url = _resolve_db_url(args.db_url)

    try:
        conn = connect(db_url)
    except Exception as e:
        print(f"Lỗi kết nối DB: {e}")
        sys.exit(1)

    # Auto-migrate: thêm cột priority nếu chưa có
    ensure_priority_column(conn)

    try:
        if args.list:
            cmd_list(conn, market=args.market, route=args.route,
                     only_priority=args.only_priority)

        elif args.preview:
            if not args.keyword:
                print("  Cần --keyword để preview.")
                sys.exit(1)
            cmd_preview(conn, args.keyword, market=args.market, route=args.route)

        elif args.add:
            if not args.market or not args.route or not args.keyword:
                print("  --add cần: --market, --route, --keyword")
                sys.exit(1)
            cmd_add(conn, args.market, args.route, args.keyword,
                    sort_order=args.sort, priority=args.priority,
                    dry_run=args.dry_run, yes=args.yes)

        elif args.delete:
            if not args.id:
                print("  --delete cần --id")
                sys.exit(1)
            cmd_delete(conn, args.id, yes=args.yes)

        elif args.toggle:
            if not args.id:
                print("  --toggle cần --id")
                sys.exit(1)
            cmd_toggle(conn, args.id)

        elif args.set_priority:
            if not args.id:
                print("  --set-priority cần --id")
                sys.exit(1)
            cmd_set_priority(conn, args.id, off=args.off)

        elif args.import_file:
            cmd_import_file(conn, args.import_file, dry_run=args.dry_run, yes=args.yes)

    except KeyboardInterrupt:
        print("\nDung (Ctrl+C)")
    except Exception as e:
        print(f"\nLoi: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
