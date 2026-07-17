from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _streamlit_secret(name: str, default: str = "") -> str:
    """Read a Streamlit secret without making local development depend on a secrets file."""
    try:
        import streamlit as st

        value: Any = st.secrets.get(name, default)
    except Exception:
        value = default
    return str(value or default).strip()


def _setting(name: str, default: str = "") -> str:
    """Environment variables override Streamlit secrets, which override defaults."""
    return os.getenv(name, _streamlit_secret(name, default)).strip()


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "BookVerse"
    app_version: str = "0.20.0-github"
    google_books_api_key: str = _setting("GOOGLE_BOOKS_API_KEY")
    open_library_contact: str = _setting("OPEN_LIBRARY_CONTACT")
    request_timeout_seconds: int = int(_setting("BOOKVERSE_HTTP_TIMEOUT", "15"))
    data_dir: Path = Path(_setting("BOOKVERSE_DATA_DIR", "data"))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "bookverse.db"


def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
