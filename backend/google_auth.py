"""Shared Google Service Account auth for gspread (local file or Render env JSON)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

BACKEND_DIR = Path(__file__).parent
PROJECT_DIR = BACKEND_DIR.parent


def _credential_paths() -> list[Path]:
    paths: list[Path] = []
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if env_path:
        paths.append(Path(env_path))
    paths.extend([
        BACKEND_DIR / "credentials.json",
        PROJECT_DIR / "credentials.json",
        Path("credentials.json"),
    ])
    return paths


def get_gspread_client():
    """Return authorized gspread client. Supports GOOGLE_CREDENTIALS_JSON on Render."""
    # 1. JSON string in env (Render dashboard)
    raw_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if raw_json:
        info = json.loads(raw_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    # 2. Config / pydantic settings
    try:
        from config import settings
        if getattr(settings, "google_credentials_json", ""):
            info = json.loads(settings.google_credentials_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            return gspread.authorize(creds)
        cfg_file = getattr(settings, "google_credentials_file", "credentials.json")
        if cfg_file:
            p = Path(cfg_file)
            if not p.is_absolute():
                for base in (BACKEND_DIR, PROJECT_DIR, Path.cwd()):
                    candidate = base / p
                    if candidate.is_file():
                        creds = Credentials.from_service_account_file(str(candidate), scopes=SCOPES)
                        return gspread.authorize(creds)
    except Exception:
        pass

    # 3. Streamlit secrets (legacy)
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES
            )
            return gspread.authorize(creds)
    except Exception:
        pass

    # 4. Credential files on disk
    for path in _credential_paths():
        if path.is_file():
            creds = Credentials.from_service_account_file(str(path), scopes=SCOPES)
            return gspread.authorize(creds)

    raise FileNotFoundError(
        "Chưa cấu hình Google Service Account. "
        "Trên Render: thêm env GOOGLE_CREDENTIALS_JSON (dán nội dung credentials.json). "
        "Local: đặt credentials.json trong thư mục backend/ hoặc ota-platform/."
    )
