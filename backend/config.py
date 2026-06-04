from __future__ import annotations

import os
import re
from urllib.parse import quote, unquote, urlparse, urlunparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _sanitize_postgres_url(url: str) -> str:
    """Sửa lỗi copy/paste: mật khẩu ...%40@@host → một ký tự @ trước hostname."""
    if "@@" in url:
        url = url.replace("@@", "@", 1)
    return url


def _append_sslmode(url: str) -> str:
    if "supabase.co" in url and "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}sslmode=require"
    return url


def _prefer_transaction_pooler(url: str) -> str:
    """
    Session pooler (:5432) giới hạn ~15 client — dễ tràn khi Render deploy chồng instance.
    Transaction pooler (:6543) phù hợp web app + NullPool.
  Set SUPABASE_SESSION_POOLER=1 để giữ :5432.
    """
    if os.getenv("SUPABASE_SESSION_POOLER", "").lower() in ("1", "true", "yes"):
        return url
    if "pooler.supabase.com" not in url or ":6543" in url:
        return url
    if ":5432" in url:
        return url.replace(":5432", ":6543", 1)
    return url


def _finalize_postgres_url(url: str) -> str:
    url = _append_sslmode(url)
    on_render = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
    use_txn = os.getenv("SUPABASE_TRANSACTION_POOLER", "true").lower() not in ("0", "false", "no")
    if "pooler.supabase.com" in url and (on_render or use_txn):
        url = _prefer_transaction_pooler(url)
    return url


def _rewrite_supabase_direct_to_pooler(url: str, pooler_host: str) -> str:
    """
    Render (và nhiều host) không ra IPv6 — db.*.supabase.co thường chỉ có AAAA.
    Session pooler dùng IPv4: aws-0-<region>.pooler.supabase.com:5432
  user postgres.<project_ref>
    """
    m = re.search(r"@db\.([a-z0-9]+)\.supabase\.co(?::5432)?", url, re.I)
    if not m:
        return url
    project_ref = m.group(1)
    parsed = urlparse(url)
    user = parsed.username or "postgres"
    if user == "postgres":
        user = f"postgres.{project_ref}"
    password = unquote(parsed.password or "")
    path = parsed.path or "/postgres"
    query = parsed.query
    auth = f"{quote(user, safe='')}:{quote(password, safe='')}" if password else quote(user, safe="")
    netloc = f"{auth}@{pooler_host}:5432"
    return _append_sslmode(urlunparse((parsed.scheme or "postgresql", netloc, path, "", query, "")))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./ota_research.db"
    secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440   # 24h
    refresh_token_expire_days: int = 30

    # Google Sheets
    google_credentials_file: str = "credentials.json"
    google_credentials_json: str = ""  # full JSON for Render env GOOGLE_CREDENTIALS_JSON
    sheet_id: str = "1sI34D88zsmSrN7Jf9fS3jh4aUvaep-blxnBR1CGq9eM"
    gid_main: str = "1729132868"
    gid_vietravel: str = "620817544"
    gid_findtourgo: str = "408521834"
    gid_route_rules: str = "58839224"
    market_rules_sheet_name: str = "Quy tắc Thị trường"

    # Scraper schedule (cron, 24h format — giờ VN)
    scraper_schedule_hour: int = 7
    scraper_schedule_minute: int = 0

    # Bearer token cho POST /api/cron/tick (GitHub Actions / cron ngoài)
    cron_secret: str = ""

    # Công ty của bạn (dùng cho so sánh đối thủ)
    company_name: str = "Vietravel"

    # Supabase pooler (Render không có IPv6) — lấy host từ Dashboard → Connect → Session pooler
    supabase_pooler_host: str = ""
    supabase_force_pooler: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        v = _sanitize_postgres_url(v)

        # Ưu tiên URL pooler riêng nếu set (khuyên dùng trên Render)
        pooler_url = (os.getenv("DATABASE_POOLER_URL") or os.getenv("SUPABASE_POOLER_URL") or "").strip()
        if pooler_url:
            if pooler_url.startswith("postgres://"):
                pooler_url = pooler_url.replace("postgres://", "postgresql://", 1)
            pooler_url = _sanitize_postgres_url(pooler_url)
            return _finalize_postgres_url(pooler_url)

        if "pooler.supabase.com" in v:
            return _finalize_postgres_url(v)

        on_render = bool(os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"))
        force = os.getenv("SUPABASE_FORCE_POOLER", "true").lower() not in ("0", "false", "no")
        if (on_render or force) and "@db." in v and ".supabase.co" in v:
            host = (os.getenv("SUPABASE_POOLER_HOST") or "").strip()
            if not host:
                region = (os.getenv("SUPABASE_REGION") or "ap-southeast-1").strip()
                host = f"aws-0-{region}.pooler.supabase.com"
            v = _rewrite_supabase_direct_to_pooler(v, host)
        if "pooler.supabase.com" in v:
            return _finalize_postgres_url(v)
        if "supabase.co" in v:
            return _append_sslmode(v)
        return v


settings = Settings()
