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

  # Preview: keyword này sẽ match bao nhiêu tour?
  python rules_offline.py --preview --keyword "koh samui"
  python rules_offline.py --preview --keyword "đà lạt, thác datanla"   # AND rule

  # Thêm rule mới
  python rules_offline.py --add --market "Thái Lan" --route "Koh Samui" --keyword "koh samui"
  python rules_offline.py --add --market "Việt Nam" --route "Miền Trung - Tây Nguyên" --keyword "đà lạt, thác datanla"

  # Thêm nhiều keywords cùng lúc (1 keyword/dòng từ file)
  python rules_offline.py --import-file rules_to_add.txt

  # Xóa rule
  python rules_offline.py --delete --id 1234

  # Bật/tắt rule
  python rules_offline.py --toggle --id 1234

Lưu ý:
  - Keywords trong 1 rule cách nhau bằng dấu phẩy = AND (tour phải có TẤT CẢ)
  - Matching dùng word-boundary: "my" KHÔNG match "myanmar"
  - KHÔNG add tuyến chung chung trùng tên thị trường (vd: thị trường "Thái Lan" thì
    không thêm tuyến "Thái Lan", chỉ được thêm "Bangkok - Pattaya", "Koh Samui" v.v.)
"""
from __future__ import annotations

import argparse
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

# ─── Cấu hình ──────────────────────────────────────────────────────────────────
DATABASE_URL = (
    "postgresql://postgres.hjoqbknulolkxqqwjxno:Thuong%402603"
    "@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
)

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


# ─── COMMANDS ──────────────────────────────────────────────────────────────────

def cmd_list(conn, market: str = "", route: str = "") -> None:
    """Hiển thị danh sách rules, lọc theo market/route nếu có."""
    sql = """
        SELECT id, thi_truong, tuyen_tour, keywords, active, sort_order
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
    sql += " ORDER BY thi_truong, tuyen_tour, sort_order, id"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    if not rows:
        print("  (Không có rule nào phù hợp)")
        return

    print(f"\n  {'ID':>6}  {'Thị trường':<18} {'Tuyến tour':<30} {'Keywords':<40} {'Active':>6}  {'Sort':>5}")
    print("  " + "─" * 105)
    prev_market = ""
    for rid, tt, tuyen, kw, active, sort in rows:
        if tt != prev_market:
            if prev_market:
                print()
            prev_market = tt
        status = "✓" if active else "✗"
        kw_disp = (kw or "")[:38]
        print(f"  {rid:>6}  {(tt or ''):<18} {(tuyen or ''):<30} {kw_disp:<40} {status:>6}  {sort:>5}")
    print(f"\n  Tổng: {len(rows)} rules")


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

    if dry_run:
        print(f"\n  [DRY-RUN] Sẽ thêm rule: {market} | {route} | {keyword!r}")
        return True

    # Xác nhận
    if not yes:
        ans = input(f"\n  Thêm rule [{market}] | [{route}] | [{keyword!r}]? (y/N) ").strip().lower()
        if ans not in ("y", "yes"):
            print("  Hủy.")
            return False

    so = sort_order if sort_order is not None else _get_max_sort_order(conn) + 1
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO route_keyword_rules (thi_truong, tuyen_tour, keywords, active, sort_order, updated_at)
               VALUES (%s, %s, %s, true, %s, %s) RETURNING id""",
            (market, route, keyword, so, now),
        )
        new_id = cur.fetchone()[0]
    conn.commit()
    print(f"\n  ✓ Đã thêm rule id={new_id}: [{market}] | [{route}] | [{keyword!r}] (sort={so})")
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
        line = line.strip()
        if not line or line.startswith("#"):
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
        parsed.append((market, route, keyword))

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

    for market, route, keyword in parsed:
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
        if dry_run:
            # Preview nhanh (không in chi tiết)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM tours WHERE nguon = ANY(%s)",
                    (list(CANONICAL_NGUON),)
                )
            print(f"  + DRY: {market} | {route} | {keyword!r} (sort={so_base})")
            added += 1
            continue

        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO route_keyword_rules (thi_truong, tuyen_tour, keywords, active, sort_order, updated_at)
                       VALUES (%s, %s, %s, true, %s, %s) RETURNING id""",
                    (market, route, keyword, so_base, now),
                )
                new_id = cur.fetchone()[0]
            conn.commit()
            print(f"  ✓ id={new_id:5d} | {market:<20} | {route:<30} | {keyword!r}")
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
    action.add_argument("--toggle", action="store_true", help="Bật/tắt rule theo --id")
    action.add_argument("--import-file", metavar="FILE", help="Import nhiều rules từ file text")

    # Params
    parser.add_argument("--market", default="", help="Thị trường (vd: 'Thái Lan')")
    parser.add_argument("--route", default="", help="Tuyến tour (vd: 'Bangkok - Pattaya')")
    parser.add_argument("--keyword", default="", help="Keyword (dùng dấu phẩy cho AND: 'kw1, kw2')")
    parser.add_argument("--id", type=int, help="ID của rule cần xóa/toggle")
    parser.add_argument("--sort", type=int, default=None, help="sort_order cho rule mới (mặc định: max+1)")
    parser.add_argument("--dry-run", action="store_true", help="Không ghi DB, chỉ xem kết quả")
    parser.add_argument("--yes", "-y", action="store_true", help="Bỏ qua bước xác nhận")
    parser.add_argument("--db-url", default=DATABASE_URL, help="Override DATABASE_URL")

    args = parser.parse_args()

    try:
        conn = connect(args.db_url)
    except Exception as e:
        print(f"Lỗi kết nối DB: {e}")
        sys.exit(1)

    try:
        if args.list:
            cmd_list(conn, market=args.market, route=args.route)

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
                    sort_order=args.sort, dry_run=args.dry_run, yes=args.yes)

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
