#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_to_cockroach.py — Di chuyển toàn bộ dữ liệu Supabase → CockroachDB.

Cách dùng:
  python migrate_to_cockroach.py            # migrate + verify
  python migrate_to_cockroach.py --verify   # chỉ so sánh số rows (không ghi)
  python migrate_to_cockroach.py --drop     # xóa hết CockroachDB rồi migrate lại

Sau khi migrate thành công:
  1. Render → Environment → DATABASE_URL = <COCKROACH_URL>
  2. Deploy lại
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    import psycopg2
    import psycopg2.extras
    import psycopg2.extensions
except ImportError:
    print("Thieu psycopg2. Chay: pip install psycopg2-binary")
    sys.exit(1)

# ─── Connection strings ────────────────────────────────────────────────────────
SUPABASE = (
    "postgresql://postgres.hjoqbknulolkxqqwjxno:Thuong%402603"
    "@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
)
COCKROACH = (
    "postgresql://thuongln:IScBLtl2u-gq466HnWqvpQ"
    "@dozing-dolphin-27297.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257/defaultdb"
    "?sslmode=require"
)
# URL dung cho SQLAlchemy (cockroachdb dialect)
COCKROACH_SQLA = (
    "cockroachdb+psycopg2://thuongln:IScBLtl2u-gq466HnWqvpQ"
    "@dozing-dolphin-27297.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257/defaultdb"
    "?sslmode=require"
)

# ─── Thứ tự bảng (tuân thủ FK) ────────────────────────────────────────────────
# FK chain:
#   workspaces ← workspace_members → users
#   route_keyword_rules ← tours (classification_rule_id)
#   route_keyword_rules ← route_rule_tokens
#   daily_snapshots ← segment_snapshots, intel_alerts
#   tours ← tour_overrides
TABLE_ORDER = [
    "users",
    "workspaces",
    "workspace_members",
    "app_kv",
    "market_keyword_rules",
    "route_keyword_rules",
    "company_alias_rules",
    "departure_alias_rules",
    "duration_alias_rules",
    "saved_views",
    "scrape_jobs",
    "tours",                  # FK → route_keyword_rules
    "route_rule_tokens",      # FK → route_keyword_rules
    "daily_snapshots",
    "segment_snapshots",      # FK → daily_snapshots
    "route_daily_metrics",
    "intel_alerts",           # FK → daily_snapshots
    "tour_overrides",         # FK → tours
]

# Cột loại trừ khi copy (sẽ tự rebuild sau):
EXCLUDE_COLS: dict[str, set[str]] = {
    # search_tsv sẽ rebuild bởi backend run_deferred_search_setup()
    "tours": {"search_tsv"},
}

BATCH = 500  # rows per INSERT batch


# ─── Helpers ──────────────────────────────────────────────────────────────────
def progress(done: int, total: int, label: str = "") -> None:
    pct = done * 100 // max(total, 1)
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"\r  [{bar}] {pct:3d}%  {done:>6}/{total}  {label}   ", end="", flush=True)


def get_columns(cur, table: str) -> list[str]:
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = %s AND table_schema = 'public'
        ORDER BY ordinal_position
    """, (table,))
    return [r[0] for r in cur.fetchall()]


def count_rows(cur, table: str) -> int:
    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cur.fetchone()[0]


def connect(url: str, label: str):
    try:
        conn = psycopg2.connect(url)
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"\n  Loi ket noi {label}: {e}")
        sys.exit(1)


# ─── Schema creation ──────────────────────────────────────────────────────────
def create_schema_in_cockroach(cockroach_sqla_url: str) -> None:
    """Tạo toàn bộ schema trong CockroachDB bằng SQLAlchemy create_all."""
    print("\n  Tao schema trong CockroachDB...")
    backend = os.path.join(os.path.dirname(__file__), "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    # Dùng cockroachdb+psycopg2 dialect (đã install sqlalchemy-cockroachdb)
    os.environ["DATABASE_URL"] = cockroach_sqla_url
    os.environ["SUPABASE_FORCE_POOLER"] = "false"

    try:
        # Reload modules with new DATABASE_URL
        for mod in list(sys.modules.keys()):
            if mod in ("config", "database", "models", "migrations"):
                del sys.modules[mod]

        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        # Load models để Base.metadata có đủ tables
        import database as db_mod  # noqa: F401
        import models  # noqa: F401

        # Tạo engine CockroachDB
        crdb_engine = create_engine(
            cockroach_sqla_url,
            poolclass=NullPool,
            pool_pre_ping=True,
        )

        db_mod.Base.metadata.create_all(bind=crdb_engine)
        print("  OK - Tables created")

        # Chay migration them cot neu thieu
        with crdb_engine.begin() as conn:
            from sqlalchemy import text, inspect
            insp = inspect(crdb_engine)
            if "users" in insp.get_table_names():
                cols = {c["name"] for c in insp.get_columns("users")}
                for stmt in [
                    "ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'analyst'",
                    "ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(512) DEFAULT ''",
                ]:
                    col = stmt.split("COLUMN IF NOT EXISTS ")[1].split(" ")[0]
                    if col not in cols:
                        try:
                            conn.execute(text(f"ALTER TABLE users {stmt}"))
                        except Exception:
                            pass
        print("  OK - Column migrations")

    except Exception as e:
        print(f"\n  Loi tao schema: {e}")
        import traceback; traceback.print_exc()
        raise


# ─── Data copy ────────────────────────────────────────────────────────────────
def copy_table(src_conn, dst_conn, table: str) -> tuple[int, int]:
    """Copy toan bo rows cua 1 table. Tra ve (src_count, inserted)."""
    src_cur = src_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    dst_cur = dst_conn.cursor()

    # Lay cot tu nguon va dich
    src_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name=%s AND table_schema='public'
        ORDER BY ordinal_position
    """, (table,))
    src_cols = [r["column_name"] for r in src_cur.fetchall()]

    dst_cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name=%s AND table_schema='public'
        ORDER BY ordinal_position
    """, (table,))
    dst_cols_set = {r[0] for r in dst_cur.fetchall()}

    # Loai tru cols khong co trong dst hoac da exclude
    exclude = EXCLUDE_COLS.get(table, set())
    cols = [c for c in src_cols if c not in exclude and c in dst_cols_set]

    if not cols:
        print(f"  SKIP {table} - khong co cot chung")
        return 0, 0

    # Count
    src_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    total = src_cur.fetchone()["count"]

    if total == 0:
        print(f"  {table:<35} 0 rows (trong)")
        return 0, 0

    # Clear dst table truoc
    dst_cur.execute(f'DELETE FROM "{table}"')
    dst_conn.commit()

    # Fetch + insert theo batch
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'

    src_cur.execute(f'SELECT {col_list} FROM "{table}"')

    inserted = 0
    batch = []
    while True:
        rows = src_cur.fetchmany(BATCH)
        if not rows:
            break
        for row in rows:
            batch.append(tuple(row[c] for c in cols))

        if batch:
            try:
                psycopg2.extras.execute_batch(dst_cur, insert_sql, batch, page_size=BATCH)
                dst_conn.commit()
                inserted += len(batch)
                progress(inserted, total, table)
                batch = []
            except Exception as e:
                dst_conn.rollback()
                print(f"\n  Loi insert {table}: {e}")
                # Retry tung row
                ok = fail = 0
                for r in batch:
                    try:
                        dst_cur.execute(insert_sql, r)
                        dst_conn.commit()
                        ok += 1
                    except Exception:
                        dst_conn.rollback()
                        fail += 1
                inserted += ok
                if fail:
                    print(f"    {fail} rows bi loi bo qua")
                batch = []

    # Flush con lai
    if batch:
        try:
            psycopg2.extras.execute_batch(dst_cur, insert_sql, batch, page_size=BATCH)
            dst_conn.commit()
            inserted += len(batch)
        except Exception as e:
            dst_conn.rollback()
            print(f"\n  Loi flush {table}: {e}")

    return total, inserted


# ─── Verify ───────────────────────────────────────────────────────────────────
def verify(src_conn, dst_conn) -> bool:
    src_cur = src_conn.cursor()
    dst_cur = dst_conn.cursor()

    print("\n  Ket qua so sanh (Supabase vs CockroachDB):")
    print(f"  {'Table':<35} {'Supabase':>10} {'CockroachDB':>12} {'Status':>8}")
    print("  " + "─" * 70)

    all_ok = True
    for table in TABLE_ORDER:
        try:
            s = count_rows(src_cur, table)
            d = count_rows(dst_cur, table)
            status = "OK" if s == d else "MISMATCH"
            if status == "MISMATCH":
                all_ok = False
            sym = "✓" if status == "OK" else "✗"
            print(f"  {sym} {table:<33} {s:>10} {d:>12}   {status}")
        except Exception as e:
            print(f"  ? {table:<33} ERR: {e}")
            all_ok = False

    return all_ok


# ─── Drop all tables in CockroachDB ───────────────────────────────────────────
def drop_all(dst_conn) -> None:
    cur = dst_conn.cursor()
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_type='BASE TABLE'
    """)
    tables = [r[0] for r in cur.fetchall()]
    if not tables:
        print("  CockroachDB da trong")
        return
    # Drop theo thu tu nguoc (FK)
    for t in reversed(TABLE_ORDER):
        if t in tables:
            try:
                cur.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
                print(f"  Dropped: {t}")
            except Exception as e:
                print(f"  Loi drop {t}: {e}")
    # Drop bat ky bang nao con lai
    for t in tables:
        if t not in TABLE_ORDER:
            try:
                cur.execute(f'DROP TABLE IF EXISTS "{t}" CASCADE')
                print(f"  Dropped (extra): {t}")
            except Exception:
                pass
    dst_conn.commit()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Migrate Supabase → CockroachDB")
    parser.add_argument("--verify", action="store_true", help="Chi so sanh so rows, khong ghi")
    parser.add_argument("--drop", action="store_true", help="Xoa het CockroachDB truoc khi migrate")
    parser.add_argument("--tables", nargs="*", help="Chi migrate 1 so bang (vd: tours rules)")
    args = parser.parse_args()

    print("=" * 65)
    print("  SUPABASE → COCKROACHDB MIGRATION")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    print("\n  Ket noi Supabase...", end=" ")
    src = connect(SUPABASE, "Supabase")
    print("OK")

    print("  Ket noi CockroachDB...", end=" ")
    dst = connect(COCKROACH, "CockroachDB")
    print("OK")

    if args.verify:
        verify(src, dst)
        src.close(); dst.close()
        return

    if args.drop:
        print("\n  Xoa toan bo tables trong CockroachDB...")
        drop_all(dst)
        print("  Xoa xong.")

    # Tao schema
    print("\n" + "─" * 65)
    create_schema_in_cockroach(COCKROACH_SQLA)

    # Reconnect sau khi create_schema (modules da reload)
    print("  Reconnect sau schema creation...", end=" ")
    try:
        dst.close()
    except Exception:
        pass
    dst = connect(COCKROACH, "CockroachDB")
    src = connect(SUPABASE, "Supabase")
    print("OK")

    # Copy data
    tables_to_migrate = args.tables if args.tables else TABLE_ORDER
    total_src = total_dst = 0

    print("\n" + "─" * 65)
    print("  Copy data:\n")
    t_start = time.time()

    for table in tables_to_migrate:
        if table not in TABLE_ORDER:
            print(f"  SKIP (unknown): {table}")
            continue

        t0 = time.time()
        s, d = copy_table(src, dst, table)
        elapsed = time.time() - t0
        total_src += s
        total_dst += d

        if s > 0:
            print(f"\r  {'✓' if s == d else '!'} {table:<35} {s:>6} → {d:>6} rows  ({elapsed:.1f}s)")
        else:
            pass  # already printed

    elapsed_total = time.time() - t_start
    print("\n" + "─" * 65)
    print(f"\n  Tong: {total_src} rows Supabase → {total_dst} rows CockroachDB ({elapsed_total:.1f}s)")

    # Final verify
    print()
    all_ok = verify(src, dst)

    src.close()
    dst.close()

    print("\n" + "=" * 65)
    if all_ok:
        print("  MIGRATION THANH CONG!")
        print()
        print("  Buoc tiep theo:")
        print("  1. Render → Settings → Environment Variables")
        print(f"     DATABASE_URL = {COCKROACH}")
        print("  2. Render → Manual Deploy")
        print("  3. Kiem tra app tai https://ota-research-platform.onrender.com")
        print()
        print("  Luu y: search_tsv se duoc rebuild tu dong khi app khoi dong")
    else:
        print("  CO BANG BI LECH! Kiem tra log phia tren.")
        print("  Chay lai: python migrate_to_cockroach.py --drop")
    print("=" * 65)


if __name__ == "__main__":
    main()
