from __future__ import annotations

import logging
from pathlib import Path

import streamlit as st

from bookverse.config import get_settings
from bookverse.cloud_database import CloudLibraryDatabase
from bookverse.views import (
    apply_theme,
    render_discover,
    render_library,
    render_profile_gate,
    render_settings_about,
    render_sidebar,
    render_stats,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "assets" / "logo_icon.png"
st.set_page_config(
    page_title=f"{settings.app_name} — Book discovery",
    page_icon=str(ICON_PATH),
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_theme()
database = CloudLibraryDatabase(settings.database_path)

if database.cloud_error:
    st.error(
        "Cloud saving is not connected. Check the Supabase bucket "
        "and the Streamlit Secrets settings."
    )

profile = render_profile_gate(database, settings)
database.set_active_user(int(profile["id"]))
page, google_api_key = render_sidebar(settings, database, profile)

if page == "Discover":
    render_discover(settings, database, google_api_key, profile)
elif page == "My Library":
    render_library(database)
elif page == "Reading Stats":
    render_stats(database)
else:
    render_settings_about(settings, database, profile)
