#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scrape_offline.py — Chạy scraper trực tiếp từ terminal, không qua API.
Kết nối thẳng PostgreSQL/CockroachDB — không tốn Egress REST.

Yêu cầu: chạy từ thư mục gốc ota-platform/
    pip install requests psycopg2-binary sqlalchemy pandas gspread google-auth

Cách dùng:
    python scrape_offline.py --source vietravel
        Scrape travel.com.vn → lưu thẳng DB (tour Vietravel)

    python scrape_offline.py --source findtourgo
        Scrape FindTourGo API → ghi Google Sheet (tab FindTourGo) như bình thường

    python scrape_offline.py --source sync-main
        Đọc tab Main từ Google Sheet → đồng bộ vào DB (phân loại lại)

    python scrape_offline.py --source all
        Chạy tuần tự: findtourgo → sync-main → vietravel

    python scrape_offline.py --source vietravel --no-sheet
        Vietravel: bỏ qua bước ghi Google Sheet (chỉ lưu DB)

    python scrape_offline.py --source vietravel --dry-run
        Scrape nhưng không lưu DB/Sheet

    python scrape_offline.py --source findtourgo --countries VN,TH,KR,JP,CN
        Chỉ scrape các quốc gia chỉ định (tất cả nếu không truyền)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

# ── Cấu hình DB ────────────────────────────────────────────────────────────────
# Production đã migrate sang CockroachDB Cloud (06/2026). KHÔNG hard-code URL ở đây.
# Backend đọc DATABASE_URL qua pydantic Settings, nên script này chỉ cần:
#   1) lấy URL từ --db-url / DATABASE_URL / DATABASE_POOLER_URL env
#   2) set lại os.environ["DATABASE_URL"] TRƯỚC khi import backend
#   3) cảnh báo nếu URL trỏ Supabase mà prod đã đổi sang CockroachDB

# Đường dẫn backend (script đặt ở thư mục gốc, backend/ là sub-folder)
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# Fix UTF-8 stdout trên Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# SECRET_KEY chỉ dùng để pass validation của backend Settings — không dùng để ký token
os.environ.setdefault("SECRET_KEY", "offline-run-secret-not-used")


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
            "     python scrape_offline.py --source vietravel --db-url 'postgresql://...'\n"
            "\n"
            "   Lấy URL từ: Render dashboard → service → Environment → DATABASE_URL\n"
            "   hoặc CockroachDB Cloud → Cluster → Connect → 'sql' driver.\n"
        )
        sys.exit(2)
    # Cảnh báo sớm nếu vẫn trỏ Supabase mà production đã chuyển sang CockroachDB
    if "cockroachlabs.cloud" not in url and "supabase" in url.lower():
        sys.stderr.write(
            "⚠️  URL đang trỏ Supabase. App production hiện chạy CockroachDB Cloud — "
            "ghi vào Supabase sẽ KHÔNG hiện trên UI Render.\n"
            "    Bấm Ctrl+C để hủy, hoặc Enter để tiếp tục.\n"
        )
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            sys.exit(2)
    return url


# ── Helpers ───────────────────────────────────────────────────────────────────
def _bar(pct: int, msg: str = "") -> None:
    filled = int(pct / 5)
    bar = "█" * filled + "░" * (20 - filled)
    print(f"\r  [{bar}] {pct:3d}%  {msg[:60]:60s}", end="", flush=True)


def _println(msg: str) -> None:
    print(f"\n{msg}")


def _sep(title: str = "") -> None:
    line = "─" * 60
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


# ── Vietravel ─────────────────────────────────────────────────────────────────
def run_vietravel(dry_run: bool = False, write_sheet: bool = True) -> dict:
    _sep("VIETRAVEL — Scrape travel.com.vn → DB")
    start = time.time()

    # Import backend modules
    try:
        from scrapers.vietravel_scraper import scrape_all_vietravel_tours
        from sheets_tour_sync import merge_dataframe_to_db
        from database import SessionLocal
    except ImportError as e:
        print(f"  Lỗi import backend: {e}")
        print(f"  Đảm bảo chạy từ thư mục ota-platform/ và đã cài deps backend.")
        return {"error": str(e)}

    def progress(pct: int, msg: str) -> None:
        _bar(pct, msg)

    print("  Đang scrape travel.com.vn…")
    try:
        df = scrape_all_vietravel_tours(progress=progress, classify=False)
    except Exception as e:
        _println(f"  Lỗi scrape Vietravel: {e}")
        return {"error": str(e)}

    _println(f"  Scraped: {len(df)} tours")

    if dry_run:
        print(f"  [DRY-RUN] Sẽ upsert {len(df)} tours vào DB. Bỏ qua.")
        return {"scraped": len(df), "dry_run": True}

    # Lưu DB
    print("  Đang upsert vào Supabase DB…")
    db = SessionLocal()
    try:
        def progress2(pct: int, msg: str) -> None:
            _bar(50 + pct // 2, msg)

        result = merge_dataframe_to_db(
            db,
            df,
            "Vietravel",
            mirror_delete=True,
            recompute_segments=True,
            progress=progress2,
        )
        _println(f"  DB: +{result.get('inserted',0)} mới  ~{result.get('updated',0)} cập nhật  -{result.get('deleted',0)} xóa")
    except Exception as e:
        _println(f"  Lỗi upsert DB: {e}")
        import traceback; traceback.print_exc()
        db.close()
        return {"scraped": len(df), "error": str(e)}
    finally:
        db.close()

    # Ghi Google Sheet (tuỳ chọn)
    if write_sheet:
        print("  Đang ghi Google Sheet…")
        try:
            from sheets_tour_sync import export_vietravel_tab_from_db
            db2 = SessionLocal()
            try:
                export_vietravel_tab_from_db(db2)
                print("  Google Sheet: ghi OK")
            finally:
                db2.close()
        except Exception as e:
            print(f"  Google Sheet: bỏ qua (lỗi: {e})")
    else:
        print("  Google Sheet: bỏ qua (--no-sheet)")

    elapsed = time.time() - start
    print(f"\n  Vietravel xong trong {elapsed:.1f}s")
    return result


# ── FindTourGo ────────────────────────────────────────────────────────────────
def run_findtourgo(
    dry_run: bool = False,
    country_codes: list[str] | None = None,
) -> dict:
    _sep("FINDTOURGO — Scrape API → Google Sheet")
    start = time.time()

    try:
        from scrapers.findtourgo_scraper import scrape_all_findtourgo_tours, write_to_google_sheet
    except ImportError as e:
        print(f"  Lỗi import backend: {e}")
        return {"error": str(e)}

    def progress(pct: int, msg: str) -> None:
        _bar(pct, msg)

    cc_label = f" ({', '.join(country_codes)})" if country_codes else " (tất cả quốc gia)"
    print(f"  Đang scrape FindTourGo API{cc_label}…")
    try:
        df = scrape_all_findtourgo_tours(
            country_codes=country_codes,
            progress=progress,
            classify=True,
        )
    except Exception as e:
        _println(f"  Lỗi scrape FindTourGo: {e}")
        import traceback; traceback.print_exc()
        return {"error": str(e)}

    if df.empty:
        _println("  Không có tour nào — kiểm tra API hoặc mạng.")
        return {"scraped": 0}

    n_companies = df["cong_ty"].nunique() if "cong_ty" in df.columns else "?"
    n_markets = int((df["thi_truong"].astype(str).str.strip() != "").sum()) if "thi_truong" in df.columns else "?"
    _println(f"  Scraped: {len(df)} tours  |  {n_companies} công ty  |  {n_markets} có thị trường/tuyến")

    if dry_run:
        print(f"  [DRY-RUN] Sẽ ghi {len(df)} tours lên Google Sheet. Bỏ qua.")
        return {"scraped": len(df), "dry_run": True}

    print("  Đang ghi lên Google Sheet tab FindTourGo…")
    try:
        write_to_google_sheet(df)
        print(f"  Google Sheet: ghi OK ({len(df)} tours)")
    except Exception as e:
        print(f"  Google Sheet: lỗi — {e}")
        import traceback; traceback.print_exc()
        return {"scraped": len(df), "sheet_error": str(e)}

    elapsed = time.time() - start
    print(f"\n  FindTourGo xong trong {elapsed:.1f}s")
    return {"scraped": len(df)}


# ── Sync Main Sheet → DB ──────────────────────────────────────────────────────
def run_sync_main(dry_run: bool = False) -> dict:
    _sep("SYNC-MAIN — Google Sheet (tab Main) → DB")
    start = time.time()

    try:
        from sheets_tour_sync import merge_sheet_source_to_db
        from database import SessionLocal
    except ImportError as e:
        print(f"  Lỗi import backend: {e}")
        return {"error": str(e)}

    if dry_run:
        print("  [DRY-RUN] Bỏ qua sync-main.")
        return {"dry_run": True}

    print("  Đang đọc Google Sheet tab Main…")
    db = SessionLocal()
    try:
        result = merge_sheet_source_to_db(
            db, "Main",
            mirror_delete=True,
            force_reclassify_all=True,
        )
        inserted = result.get("inserted", 0)
        updated = result.get("updated", 0)
        deleted = result.get("deleted", 0)
        print(f"  DB: +{inserted} mới  ~{updated} cập nhật  -{deleted} xóa")
    except Exception as e:
        print(f"  Lỗi sync-main: {e}")
        import traceback; traceback.print_exc()
        db.close()
        return {"error": str(e)}
    finally:
        db.close()

    elapsed = time.time() - start
    print(f"  sync-main xong trong {elapsed:.1f}s")
    return result


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chạy scraper OTA offline (không qua API backend)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python scrape_offline.py --source vietravel
  python scrape_offline.py --source findtourgo --countries VN,TH,KR,JP,CN
  python scrape_offline.py --source sync-main
  python scrape_offline.py --source all
  python scrape_offline.py --source vietravel --dry-run
  python scrape_offline.py --source vietravel --no-sheet
        """,
    )
    parser.add_argument(
        "--source",
        required=True,
        choices=["vietravel", "findtourgo", "sync-main", "all"],
        help="Nguồn cần scrape/đồng bộ",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape nhưng không ghi DB / Sheet",
    )
    parser.add_argument(
        "--no-sheet",
        action="store_true",
        help="(Vietravel) Bỏ qua bước ghi Google Sheet",
    )
    parser.add_argument(
        "--countries",
        default="",
        help="(FindTourGo) Danh sách ISO country code, phân cách bằng dấu phẩy. Mặc định: tất cả",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DATABASE_URL (mặc định lấy từ env var DATABASE_URL hoặc DATABASE_POOLER_URL)",
    )
    args = parser.parse_args()

    # Resolve DB URL: --db-url > DATABASE_URL env > DATABASE_POOLER_URL env > error.
    # Cảnh báo nếu URL trỏ Supabase (production đã sang CockroachDB).
    # PHẢI set env TRƯỚC khi import backend modules (config.Settings đọc 1 lần lúc import).
    db_url = _resolve_db_url(args.db_url)
    os.environ["DATABASE_URL"] = db_url

    country_list: list[str] | None = None
    if args.countries.strip():
        country_list = [c.strip().upper() for c in args.countries.split(",") if c.strip()]

    total_start = time.time()
    _sep()
    print(f"  scrape_offline.py  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  source={args.source}  dry_run={args.dry_run}")
    _sep()

    try:
        if args.source == "vietravel":
            run_vietravel(dry_run=args.dry_run, write_sheet=not args.no_sheet)

        elif args.source == "findtourgo":
            run_findtourgo(dry_run=args.dry_run, country_codes=country_list)

        elif args.source == "sync-main":
            run_sync_main(dry_run=args.dry_run)

        elif args.source == "all":
            # Thứ tự: FindTourGo (ghi Sheet) → sync-main (Sheet→DB) → Vietravel (scrape→DB)
            r1 = run_findtourgo(dry_run=args.dry_run, country_codes=country_list)
            if "error" not in r1:
                print("\n  FindTourGo xong. Chờ 5 giây trước sync-main…")
                if not args.dry_run:
                    time.sleep(5)
                run_sync_main(dry_run=args.dry_run)
            else:
                print("  FindTourGo lỗi — bỏ qua sync-main, tiếp tục Vietravel")
            run_vietravel(dry_run=args.dry_run, write_sheet=not args.no_sheet)

        total = time.time() - total_start
        _sep()
        print(f"  Tong thoi gian: {total:.1f}s")
        _sep()

    except KeyboardInterrupt:
        print("\n\n  Dung boi nguoi dung (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        print(f"\n  LOI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
