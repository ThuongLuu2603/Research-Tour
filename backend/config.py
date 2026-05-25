from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Scraper schedule (cron, 24h format)
    scraper_schedule_hour: int = 7
    scraper_schedule_minute: int = 0

    # Công ty của bạn (dùng cho so sánh đối thủ)
    company_name: str = "Vietravel"

    @field_validator("database_url", mode="before")
    @classmethod
    def fix_postgres_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v


settings = Settings()
