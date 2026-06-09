#!/usr/bin/env python3
"""Migrate dữ liệu từ CockroachDB Serverless sang Postgres self-host (Vietnix).

Cách dùng:
    python migrate-from-crdb.py \
        --source 'cockroachdb+psycopg2://user:pass@host:26257/defaultdb?sslmode=verify-full' \
        --target 'postgresql://ota:pass@127.0.0.1:5432/ota' \
        [--dry-run]

Logic:
    1. Kết nối cả 2 DB
    2. init_db() trên target để tạo schema (Base.metadata.create_all)
    3. Với mỗi bảng (theo thứ tự FK an toàn): SELECT * → INSERT batch 500 rows
    4. Sau cùng: setval() cho tất cả sequences (vì ID gốc từ unique_rowid > MAX seq)
    5. Verify row counts khớp

Yêu cầu: chạy TỪ MÁY VPS (có sẵn psycopg2 + sqlalchemy + project deps).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Cho phép import backend.*
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("migrate-crdb")

# Thứ tự bảng phải tôn trọng FK (parent trước child)
TABLE_ORDER = [
    # Master/lookup tables không phụ thuộc
    "users",
    "workspaces",
    "workspace_members",
    "app_kv",
    "job_lock",
    # Rule tables (có thể reference users)
    "market_keyword_rules",
    "route_keyword_rules",
    "company_alias_rules",
    "departure_alias_rules",
    "duration_alias_rules",
    "date_format_rules",
    "festival_tour_mapping_rules",
    # Festival data
    "festivals",
    # Tour core
    "tours",
    "route_rule_tokens",
    # Tour-derived
    "tour_overrides",
    "tour_segments",
    "route_daily_metrics",
    "daily_snapshots",
    "segment_snapshots",
    "intel_alerts",
    "saved_views",
    # Scrape history
    "scrape_jobs",
]

BATCH_SIZE = 500


def get_existing_tables(engine, tables: list[str]) -> list[str]:
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    return [t for t in tables if t in existing]


def copy_table(src_session, dst_session, table_name: str, dry_run: bool = False) -> tuple[int, int]:
    """Copy 1 table. Return (rows_read, rows_inserted)."""
    # Đếm trước
    src_count = src_session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar() or 0
    if src_count == 0:
        log.info("  %s: 0 rows (skip)", table_name)
        return 0, 0

    # Lấy column names từ target (tránh schema mismatch)
    insp = inspect(dst_session.bind)
    cols = [c["name"] for c in insp.get_columns(table_name)]
    col_list = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    insert_sql = text(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})")

    # Select theo column list xác định (không SELECT * — có thể dư cột)
    select_sql = text(f"SELECT {col_list} FROM {table_name}")

    inserted = 0
    batch = []
    rows = src_session.execute(select_sql)
    t0 = time.time()
    for row in rows:
        d = dict(zip(cols, row, strict=True))
        batch.append(d)
        if len(batch) >= BATCH_SIZE:
            if not dry_run:
                dst_session.execute(insert_sql, batch)
                dst_session.commit()
            inserted += len(batch)
            batch.clear()
            if inserted % (BATCH_SIZE * 10) == 0:
                log.info("    %s: %d/%d (%.1f%%)", table_name, inserted, src_count, 100 * inserted / src_count)
    if batch:
        if not dry_run:
            dst_session.execute(insert_sql, batch)
            dst_session.commit()
        inserted += len(batch)

    elapsed = time.time() - t0
    log.info("  %s: %d rows copied in %.1fs", table_name, inserted, elapsed)
    return src_count, inserted


def resync_sequences(dst_session) -> None:
    """Sau khi insert với ID gốc (từ unique_rowid), sync sequence để INSERT mới
    không đụng PK conflict. Chỉ áp dụng cho cột id integer có sequence."""
    log.info("▸ Resync sequences…")
    insp = inspect(dst_session.bind)
    for table in insp.get_table_names():
        cols = insp.get_columns(table)
        for col in cols:
            if col["name"] != "id":
                continue
            # Kiểm tra có sequence không
            seq_name = dst_session.execute(
                text(f"SELECT pg_get_serial_sequence(:t, 'id')"),
                {"t": table},
            ).scalar()
            if not seq_name:
                continue
            max_id = dst_session.execute(text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0
            new_val = max_id + 1
            dst_session.execute(text(f"SELECT setval(:seq, :v, false)"), {"seq": seq_name, "v": new_val})
            log.info("  %s.%s → setval(%d)", table, seq_name, new_val)
    dst_session.commit()


def verify_counts(src_session, dst_session, tables: list[str]) -> bool:
    log.info("▸ Verify row counts…")
    ok = True
    for t in tables:
        src_n = src_session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0
        dst_n = dst_session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() or 0
        marker = "✓" if src_n == dst_n else "✗"
        log.info("  %s %s: source=%d target=%d", marker, t, src_n, dst_n)
        if src_n != dst_n:
            ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="Migrate CRDB → Postgres for OTA platform")
    ap.add_argument("--source", required=True, help="CockroachDB Serverless URL")
    ap.add_argument("--target", required=True, help="Postgres self-host URL (Vietnix)")
    ap.add_argument("--dry-run", action="store_true", help="Đọc + đếm, không ghi")
    ap.add_argument("--skip-schema", action="store_true", help="Bỏ qua bước init_db schema")
    args = ap.parse_args()

    # Auto-detect CockroachDB và dùng dialect cockroachdb+psycopg2 — SQLAlchemy
    # postgresql dialect không parse được CRDB version string "CockroachDB CCL v25.4..."
    # → AssertionError. CRDB dialect dùng cùng psycopg2 driver, không strict version check.
    if "cockroachlabs.cloud" in args.source and args.source.startswith("postgresql://"):
        args.source = "cockroachdb+psycopg2://" + args.source[len("postgresql://"):]
        log.info("Auto-converted source URL: postgresql:// → cockroachdb+psycopg2://")

    log.info("Source: %s", args.source[:60] + "…")
    log.info("Target: %s", args.target[:60] + "…")
    log.info("Dry run: %s", args.dry_run)

    # Engines
    src_engine = create_engine(args.source, pool_pre_ping=True)
    dst_engine = create_engine(args.target, pool_pre_ping=True)

    # 1. Init schema trên target (chạy database.init_db)
    if not args.skip_schema and not args.dry_run:
        log.info("▸ Init schema trên target…")
        import os

        os.environ["DATABASE_URL"] = args.target
        # Reload settings
        from importlib import reload

        import config
        reload(config)
        from database import init_db, run_deferred_db_maintenance  # noqa: E402

        init_db()
        log.info("  schema OK")

    # 2. Sessions
    SrcSession = sessionmaker(bind=src_engine)
    DstSession = sessionmaker(bind=dst_engine)
    src = SrcSession()
    dst = DstSession()

    try:
        # 3. Copy tables
        tables = get_existing_tables(src_engine, TABLE_ORDER)
        log.info("▸ Tables to copy: %d", len(tables))

        # Disable triggers/constraints tạm thời (giúp INSERT nhanh + tránh FK race)
        if not args.dry_run:
            log.info("▸ Defer constraints…")
            dst.execute(text("SET session_replication_role = replica;"))
            dst.commit()

        total_src, total_dst = 0, 0
        for t in tables:
            s, d = copy_table(src, dst, t, dry_run=args.dry_run)
            total_src += s
            total_dst += d

        # Re-enable constraints
        if not args.dry_run:
            dst.execute(text("SET session_replication_role = DEFAULT;"))
            dst.commit()
            # Resync sequences
            resync_sequences(dst)

        # 4. Verify
        log.info("Total: source=%d, target=%d", total_src, total_dst)
        if not args.dry_run:
            ok = verify_counts(src, dst, tables)
            if not ok:
                log.error("✗ Row counts mismatch — review trước khi cutover")
                return 1

        log.info("✓ Migration DONE")
        return 0
    finally:
        src.close()
        dst.close()


if __name__ == "__main__":
    sys.exit(main())
