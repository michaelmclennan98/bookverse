from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from .cache import (
    cached_enrich_catalogue_book,
    cached_enrich_library_book,
    cached_personalised,
    cached_search,
    cached_similar,
)
from .config import Settings, get_settings
from .database import DEFAULT_SHELVES, LibraryDatabase
from .models import Book
from .personalization import build_taste_seed, taste_fingerprint, taste_summary
from .recommender import favourite_categories, profile_summary, rank_smart_results
from .smart_search import SmartSearchPlan, parse_smart_query

LANGUAGES = {
    "Any language": "",
    "English": "en",
    "French": "fr",
    "German": "de",
    "Spanish": "es",
    "Italian": "it",
    "Portuguese": "pt",
}

QUICK_DISCOVERY = (
    "Epic fantasy", "Dark academia", "Cozy mystery", "Historical fiction",
    "Science fiction", "Horror", "Romance", "Biography",
)


COMMON_NICHES = (
    "Contemporary romance", "Dark romance", "Romantasy", "Epic fantasy",
    "Dark fantasy", "Urban fantasy", "Science fiction", "Dystopian",
    "Psychological thriller", "Crime", "Cozy mystery", "Historical fiction",
    "Horror", "Extreme horror", "Gothic horror", "Young adult",
    "Mental-health fiction", "Literary fiction", "Biography", "True crime",
)


NAVIGATION_PAGES = ("Discover", "My Library", "Reading Stats", "Settings & About")


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_FULL_PATH = ASSETS_DIR / "logo_full.png"
LOGO_ICON_PATH = ASSETS_DIR / "logo_icon.png"


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: linear-gradient(180deg, #111318 0%, #171a21 100%); }
        [data-testid="stSidebar"] { background: #0d0f14; }
        .block-container { max-width: 1480px; padding-top: 1.7rem; }
        h1, h2, h3 { letter-spacing: -0.02em; }
        .book-meta { color: #b6bdc9; font-size: 0.88rem; }
        .book-title { font-weight: 750; line-height: 1.15; min-height: 2.3rem; }
        .source-pill {
            display: inline-block; border: 1px solid #3b4252; border-radius: 999px;
            padding: 0.1rem 0.45rem; color: #cbd5e1; font-size: 0.72rem;
        }
        .brand-loader {
            display: flex; align-items: center; gap: 0.9rem; padding: 0.9rem 1rem;
            border: 1px solid #303642; border-radius: 1rem; background: rgba(27, 33, 43, 0.95);
            margin: 0.6rem 0 1rem 0;
        }
        .brand-loader img { width: 58px; height: 58px; object-fit: contain; animation: bob 1.8s ease-in-out infinite; }
        .brand-loader .loader-title { font-size: 1rem; font-weight: 700; }
        .brand-loader .loader-sub { color: #b6bdc9; font-size: 0.9rem; }
        .brand-note { color: #b6bdc9; font-size: 0.95rem; }
        @keyframes bob {
            0% { transform: translateY(0px); }
            50% { transform: translateY(-6px); }
            100% { transform: translateY(0px); }
        }
        .bookcase-frame {
            padding: 1rem 1rem 0.2rem; border: 10px solid #5b321c; border-radius: 0.8rem;
            background: radial-gradient(circle at 50% 5%, #3b2619 0%, #21140e 72%);
            box-shadow: inset 0 0 0 3px #9a6035, inset 0 0 32px rgba(0,0,0,.72);
            margin: 0.8rem 0 1.3rem;
        }
        .bookcase-nameplate {
            width: fit-content; margin: -0.15rem auto 1rem; padding: .35rem .95rem;
            border: 2px solid #c9954f; border-radius: .35rem; color: #f5deb3;
            background: #4a2817; font-weight: 750; letter-spacing: .04em;
            box-shadow: 0 2px 5px rgba(0,0,0,.5);
        }
        .bookcase-row {
            position: relative; display: flex; align-items: flex-end; gap: 5px; min-height: 205px;
            padding: 0 14px 19px; overflow-x: auto; overflow-y: hidden;
            scrollbar-color: #7e4b2c #21140e;
        }
        .bookcase-row::after {
            content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 18px;
            border-top: 3px solid #c07b42; border-bottom: 4px solid #3f2112;
            background: linear-gradient(180deg, #9a5b31 0%, #65371f 55%, #3f2112 100%);
            box-shadow: 0 7px 12px rgba(0,0,0,.65), inset 0 2px 2px rgba(255,255,255,.16);
            z-index: 1;
        }
        .book-spine {
            --spine: #234c78; --spine-dark: #10283f;
            position: relative; z-index: 2; flex: 0 0 auto; display: flex; align-items: center;
            justify-content: center; height: var(--book-height, 176px); width: var(--book-width, 42px);
            padding: 7px 5px; border: 1px solid rgba(255,255,255,.18); border-radius: 4px 4px 2px 2px;
            background: linear-gradient(90deg, var(--spine-dark) 0%, var(--spine) 14%, var(--spine) 82%, var(--spine-dark) 100%);
            color: #fff8df !important; text-decoration: none !important; text-shadow: 0 1px 2px rgba(0,0,0,.9);
            box-shadow: inset 2px 0 rgba(255,255,255,.12), inset -2px 0 rgba(0,0,0,.32), 2px 2px 5px rgba(0,0,0,.55);
            transition: transform .16s ease, filter .16s ease;
        }
        .book-spine:hover, .book-spine:focus {
            transform: translateY(-10px) rotate(-1deg); filter: brightness(1.18); z-index: 4; outline: 2px solid #e2ad57;
        }
        .book-spine-title {
            writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; max-height: calc(var(--book-height, 176px) - 22px);
            font-size: .78rem; font-weight: 750; letter-spacing: .015em;
        }
        .book-spine::before, .book-spine::after {
            content: ""; position: absolute; left: 4px; right: 4px; height: 2px; background: rgba(255,229,160,.65);
        }
        .book-spine::before { top: 9px; }
        .book-spine::after { bottom: 9px; }
        .bookcase-shelf-label {
            position: absolute; z-index: 3; right: 10px; bottom: 2px; font-size: .68rem; color: #f0d3a0;
            background: #4b2917; border: 1px solid #bb7a41; border-radius: .25rem; padding: 1px 7px;
        }
        .bookcase-empty-space { color: #c9b79f; padding: 4.5rem 1rem 5.5rem; text-align: center; }
        .st-key-phone_controls_toggle { margin-bottom: .25rem; }
        .st-key-phone_controls_panel {
            padding: .85rem 1rem; border: 1px solid #39414e; border-left: 5px solid #d8a657;
            border-radius: 1rem; background: rgba(30, 34, 43, .96); margin-bottom: 1rem;
        }
        div[data-testid="stMetric"] { background: #1e222b; border: 1px solid #303642; padding: 0.8rem; border-radius: 0.8rem; }

        @media (max-width: 768px) {
            [data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"],
            button[data-testid="stSidebarCollapseButton"] {
                display: none !important;
            }

            .stApp { overflow-x: hidden; }
            .block-container {
                max-width: 100% !important;
                padding: .65rem .7rem calc(1.4rem + env(safe-area-inset-bottom)) !important;
            }

            .st-key-phone_controls_toggle {
                position: sticky;
                top: calc(3.75rem + env(safe-area-inset-top));
                z-index: 950;
                margin: 3.6rem 0 .7rem;
                padding: .55rem .75rem;
                background: rgba(13, 15, 20, .98);
                border: 1px solid #303642;
                border-radius: .85rem;
                backdrop-filter: blur(14px);
            }
            .st-key-phone_controls_toggle label { min-height: 44px; }
            .st-key-phone_controls_panel {
                padding: .8rem !important; margin-inline: -.1rem;
                border-radius: .85rem;
            }
            .st-key-phone_controls_panel [data-testid="stHorizontalBlock"] {
                gap: .5rem !important;
            }

            /* Make all important controls finger-friendly. */
            .stButton > button, .stFormSubmitButton > button,
            [data-testid="stLinkButton"] > a { min-height: 46px; }
            div[data-baseweb="select"] > div, input, textarea { min-height: 46px; }
            [data-testid="stCheckbox"] label { min-height: 42px; padding-block: .25rem; }

            /* Stack search and action layouts cleanly on a narrow screen. */
            h1 { font-size: 1.75rem !important; }
            h2 { font-size: 1.4rem !important; }
            .brand-loader { align-items: flex-start; }
            .brand-loader img { width: 46px; height: 46px; }

            /* Keep the 15-book shelf intact and make it swipe horizontally. */
            [class*="st-key-live_shelf_row_"] {
                overflow-x: auto !important; overflow-y: visible !important;
                -webkit-overflow-scrolling: touch;
                padding-bottom: 28px !important;
            }
            [class*="st-key-live_shelf_row_"] > div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"],
            [class*="st-key-live_shelf_row_"] div[data-testid="stHorizontalBlock"] {
                min-width: 1020px !important; flex-wrap: nowrap !important;
            }
            .st-key-live_bookcase_frame {
                margin-inline: -.35rem !important; padding-inline: .45rem !important;
                border-width: 6px !important;
            }

            /* Dialogs and book information use the full phone width. */
            [data-testid="stDialog"] > div { width: calc(100vw - 1rem) !important; max-width: none !important; }
            [data-testid="stDialog"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_profile_gate(db: LibraryDatabase, settings: Settings) -> dict[str, Any]:
    active_id = st.session_state.get("active_profile_id")
    if active_id is not None:
        profile = db.get_profile(int(active_id))
        if profile:
            return profile
        st.session_state.pop("active_profile_id", None)

    st.sidebar.empty()
    left, centre, right = st.columns([1, 1.35, 1])
    with centre:
        st.image(str(LOGO_FULL_PATH), width=230)
        st.title("Welcome to BookVerse")
        st.write("Unlock your reading profile or create one to keep libraries and recommendations separate.")

        profiles = db.list_profiles()
        unlock_tab, create_tab = st.tabs(("Unlock profile", "Create profile"))

        with unlock_tab:
            if not profiles:
                st.info("No profiles exist yet. Create the first one in the next tab.")
            else:
                labels = {
                    f"{profile['display_name']} (@{profile['username']})": profile
                    for profile in profiles
                }
                selected_label = st.selectbox("Profile", tuple(labels), key="gate_profile_select")
                with st.form("unlock_profile_form"):
                    pin = st.text_input("PIN", type="password")
                    unlock = st.form_submit_button("Unlock BookVerse", type="primary", use_container_width=True)
                if unlock:
                    selected = labels[selected_label]
                    if db.verify_profile_pin(int(selected["id"]), pin):
                        st.session_state.active_profile_id = int(selected["id"])
                        st.session_state.pop("personalised_results", None)
                        st.rerun()
                    else:
                        st.error("Incorrect PIN.")

        with create_tab:
            st.caption("Choose exact books from the live catalogue. They will be added to this profile as Finished and used to learn your taste.")
            display_name = st.text_input("Display name", placeholder="Michael", key="create_display_name")
            username = st.text_input("Username", placeholder="mikey", key="create_username")
            new_pin = st.text_input("Create PIN", type="password", help="At least 4 characters", key="create_pin")
            confirm_pin = st.text_input("Confirm PIN", type="password", key="create_confirm_pin")
            niches = st.multiselect(
                "Favourite niches",
                COMMON_NICHES,
                placeholder="Choose the genres and niches you read most",
                key="create_niches",
            )
            custom_niches = st.text_input(
                "Other niches",
                placeholder="e.g. splatterpunk, closed-door romance, naval history",
                key="create_custom_niches",
            )

            st.markdown("#### Your top books")
            st.caption(
                "Type only the book title, then press Enter or click Search. "
                "Choose the exact title and author from the catalogue results. Add up to 10."
            )

            with st.form("profile_book_search_form", clear_on_submit=False):
                book_query = st.text_input(
                    "Book title",
                    placeholder="e.g. Playground",
                    key="profile_book_query",
                )
                search_books = st.form_submit_button(
                    "Search book catalogue",
                    type="secondary",
                    use_container_width=True,
                )

            if search_books:
                query_value = book_query.strip()
                st.session_state.profile_book_matches = []
                st.session_state.profile_book_messages = []
                st.session_state.profile_book_search_ran = True

                if not query_value:
                    st.warning("Enter a book title first.")
                else:
                    loader = st.empty()
                    loader.markdown(
                        _loader_html(
                            "Finding that book…",
                            "Searching Google Books and Open Library for exact title and author matches.",
                        ),
                        unsafe_allow_html=True,
                    )
                    title_payloads: list[dict] = []
                    title_messages: list[str] = []
                    keyword_payloads: list[dict] = []
                    keyword_messages: list[str] = []
                    try:
                        title_payloads, title_messages = cached_search(
                            query_value,
                            "Title",
                            "Both",
                            24,
                            "",
                            "relevance",
                            "",
                            settings.google_books_api_key,
                            settings.open_library_contact,
                            settings.request_timeout_seconds,
                            0,
                        )

                        # Some catalogue records have weak title indexing. A second
                        # keyword pass improves recall, while exact-title matches are
                        # still displayed first.
                        if len(title_payloads) < 12:
                            keyword_payloads, keyword_messages = cached_search(
                                query_value,
                                "Keyword",
                                "Both",
                                24,
                                "",
                                "relevance",
                                "",
                                settings.google_books_api_key,
                                settings.open_library_contact,
                                settings.request_timeout_seconds,
                                0,
                            )
                    finally:
                        loader.empty()

                    combined_payloads: list[dict] = []
                    seen_uids: set[str] = set()
                    for payload in [*title_payloads, *keyword_payloads]:
                        try:
                            candidate = Book.from_dict(payload)
                        except (TypeError, ValueError, KeyError):
                            continue
                        if candidate.uid in seen_uids:
                            continue
                        seen_uids.add(candidate.uid)
                        combined_payloads.append(candidate.to_dict())

                    st.session_state.profile_book_matches = combined_payloads[:36]
                    st.session_state.profile_book_messages = list(
                        dict.fromkeys([*title_messages, *keyword_messages])
                    )

            for message in st.session_state.get("profile_book_messages", []):
                st.warning(message)

            matches = [Book.from_dict(item) for item in st.session_state.get("profile_book_matches", [])]
            if matches:
                option_labels: list[str] = []
                option_map: dict[str, Book] = {}
                for index, book in enumerate(matches):
                    label = f"{book.display_title} — {book.author_text}"
                    if book.published_year:
                        label += f" ({book.published_year})"
                    if book.source:
                        label += f" · {book.source}"
                    # Ensure repeated editions do not overwrite each other.
                    unique_label = label if label not in option_map else f"{label} · edition {index + 1}"
                    option_labels.append(unique_label)
                    option_map[unique_label] = book

                chosen_label = st.selectbox(
                    "Choose the exact book",
                    option_labels,
                    key="profile_book_choice",
                )
                chosen = option_map[chosen_label]
                preview_cover, preview_text = st.columns([1, 3])
                with preview_cover:
                    if chosen.best_cover:
                        st.image(chosen.best_cover, width=90)
                    else:
                        st.caption("No cover")
                with preview_text:
                    st.markdown(f"**{chosen.display_title}**")
                    st.caption(chosen.author_text)
                    details = []
                    if chosen.published_year:
                        details.append(str(chosen.published_year))
                    if chosen.page_count:
                        details.append(f"{chosen.page_count:,} pages")
                    if chosen.average_rating is not None:
                        details.append(f"★ {chosen.average_rating:.1f}")
                    if details:
                        st.caption(" · ".join(details))

                if st.button(
                    "Add selected book to my top books",
                    type="primary",
                    use_container_width=True,
                    key=f"profile_add_top_book_{chosen.uid}",
                ):
                    selected_books = list(st.session_state.get("profile_top_books", []))
                    if any(item.get("uid") == chosen.uid for item in selected_books):
                        st.info("That exact book is already selected.")
                    elif len(selected_books) >= 10:
                        st.warning("You can choose up to 10 top books.")
                    else:
                        selected_books.append(chosen.to_dict())
                        st.session_state.profile_top_books = selected_books
                        st.session_state.profile_book_matches = []
                        st.session_state.profile_book_messages = []
                        st.session_state.pop("profile_book_search_ran", None)
                        st.rerun()
            elif st.session_state.get("profile_book_search_ran"):
                st.warning(
                    "No catalogue matches were found. Google Books may be temporarily unavailable, "
                    "and Open Library returned no title match. Try the title again, use fewer words, "
                    "or wait a moment and search once more."
                )

            selected_payloads = list(st.session_state.get("profile_top_books", []))
            if selected_payloads:
                st.markdown("**Selected top books**")
                for index, payload in enumerate(selected_payloads):
                    book = Book.from_dict(payload)
                    name_col, remove_col = st.columns([5, 1])
                    name_col.write(f"{index + 1}. **{book.display_title}** — {book.author_text}")
                    if remove_col.button("Remove", key=f"remove_profile_top_{book.uid}_{index}"):
                        st.session_state.profile_top_books = [
                            item for item in selected_payloads if item.get("uid") != book.uid
                        ]
                        st.rerun()
            else:
                st.info("No top books selected yet. You can still create the profile, but recommendations improve when you add a few.")

            create = st.button("Create locked profile", type="primary", use_container_width=True, key="create_locked_profile")
            if create:
                if new_pin != confirm_pin:
                    st.error("The PINs do not match.")
                else:
                    extra_niches = [value.strip() for value in custom_niches.split(",") if value.strip()]
                    selected_books = [Book.from_dict(payload) for payload in selected_payloads]
                    top_books = [f"{book.display_title} — {book.author_text}" for book in selected_books]
                    try:
                        profile = db.create_profile(
                            username=username,
                            display_name=display_name,
                            pin=new_pin,
                            favourite_niches=[*niches, *extra_niches],
                            top_books=top_books,
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        db.set_active_user(int(profile["id"]))
                        for book in selected_books:
                            db.save_entry(
                                book,
                                "Finished",
                                progress_pages=int(book.page_count or 0),
                            )
                        st.session_state.active_profile_id = int(profile["id"])
                        st.session_state.pop("personalised_fingerprint", None)
                        st.session_state.pop("personalised_results", None)
                        for key in (
                            "profile_top_books",
                            "profile_book_matches",
                            "profile_book_messages",
                            "profile_book_query",
                        ):
                            st.session_state.pop(key, None)
                        st.success("Profile created. Your selected top books were marked as Finished and added to your bookcase.")
                        st.rerun()

    st.stop()
    raise RuntimeError("Streamlit execution should have stopped")


def _set_active_page(page: str) -> None:
    """Queue a confirmed navigation choice without changing the browser URL."""
    if page not in NAVIGATION_PAGES:
        page = "Discover"
    st.session_state.active_page = page
    st.session_state.phone_active_page = page
    # The desktop radio may already be instantiated in this run. Queue its
    # widget-state update for the next rerun instead of mutating it immediately.
    st.session_state.pending_sidebar_navigation = page


def _lock_active_profile(db: LibraryDatabase) -> None:
    st.session_state.pop("active_profile_id", None)
    for key in list(st.session_state):
        if key.startswith(("search_", "similar_", "personalised_", "phone_")):
            st.session_state.pop(key, None)
    db.set_active_user(None)


def render_sidebar(
    settings: Settings,
    db: LibraryDatabase,
    profile: dict[str, Any],
) -> tuple[str, str]:
    pending_page = st.session_state.pop("pending_sidebar_navigation", None)
    if pending_page in NAVIGATION_PAGES:
        # This runs before the radio widget is created, so Streamlit permits the
        # state synchronisation. It mirrors the proven staged phone-nav pattern.
        st.session_state.sidebar_navigation = pending_page
        st.session_state.active_page = pending_page
        st.session_state.phone_active_page = pending_page

    if st.session_state.get("active_page") not in NAVIGATION_PAGES:
        st.session_state.active_page = "Discover"

    active_page = str(st.session_state.active_page)

    brand_col, title_col = st.sidebar.columns([1, 2.3])
    with brand_col:
        st.image(str(LOGO_ICON_PATH), width=56)
    with title_col:
        st.markdown("## BookVerse")
        st.caption(f"{profile['display_name']} · @{profile['username']}")

    desktop_page = st.sidebar.radio(
        "Navigate",
        NAVIGATION_PAGES,
        key="sidebar_navigation",
        label_visibility="collapsed",
    )
    if desktop_page != active_page:
        _set_active_page(desktop_page)
        active_page = desktop_page

    if st.sidebar.button("🔒 Lock / switch profile", use_container_width=True):
        _lock_active_profile(db)
        st.rerun()

    st.sidebar.divider()
    st.sidebar.caption("Catalogue connections")
    api_key = settings.google_books_api_key
    if api_key:
        st.sidebar.success("Google Books enabled", icon="✅")
    else:
        st.sidebar.info("Using Open Library only", icon="ℹ️")
    saved_count = len(db.list_entries("All"))
    st.sidebar.caption(f"Your library: **{saved_count} books**")
    st.sidebar.caption(f"Local database: `{settings.database_path}`")
    st.sidebar.caption("Profiles are protected with a local PIN. Add hosted authentication before public deployment.")

    # Phone fallback controls modelled on the user's Frog dashboard. The toggle
    # survives Streamlit reruns. Dropdown changes are staged and only applied
    # after pressing Go, so choosing an option cannot unexpectedly navigate.
    if "show_phone_controls" not in st.session_state:
        st.session_state.show_phone_controls = False
    if st.session_state.get("phone_active_page") not in NAVIGATION_PAGES:
        st.session_state.phone_active_page = active_page
    if st.session_state.get("mobile_page_selector") not in NAVIGATION_PAGES:
        st.session_state.mobile_page_selector = str(st.session_state.phone_active_page)

    with st.container(key="phone_controls_toggle"):
        st.checkbox(
            "📱 Show phone controls",
            key="show_phone_controls",
            help="Turn this on when the Streamlit sidebar is hidden on your phone. It stays open across reruns.",
        )

    if bool(st.session_state.get("show_phone_controls", False)):
        with st.container(key="phone_controls_panel"):
            st.markdown("#### 📱 Phone controls")
            st.caption("Choose the page, then press Go. Selecting an option does not navigate by itself.")
            profile_col, page_col = st.columns([1, 1])
            with profile_col:
                profile_action = st.selectbox(
                    "Profile",
                    (f"{profile['display_name']} (@{profile['username']})", "🔒 Lock / switch profile"),
                    key="mobile_profile_selector",
                    help="Choose Lock / switch profile and press Go to return to the PIN screen.",
                )
            with page_col:
                staged_page = st.selectbox(
                    "Navigate",
                    NAVIGATION_PAGES,
                    key="mobile_page_selector",
                    help="This page is staged until you press Go.",
                )

            go_col, status_col = st.columns([1, 2.4], vertical_alignment="center")
            with go_col:
                go_pressed = st.button(
                    "Go",
                    key="mobile_go_button",
                    type="primary",
                    use_container_width=True,
                )
            with status_col:
                st.caption(
                    f"Current page: **{st.session_state.phone_active_page}** · "
                    f"Library: **{saved_count} books**"
                )

            if go_pressed:
                if profile_action == "🔒 Lock / switch profile":
                    _lock_active_profile(db)
                    st.rerun()
                _set_active_page(staged_page)
                st.rerun()

            if api_key:
                st.success("Google Books enabled", icon="✅")
            else:
                st.info("Using Open Library only", icon="ℹ️")

    return str(st.session_state.active_page), api_key


def render_discover(
    settings: Settings,
    db: LibraryDatabase,
    api_key: str,
    profile: dict[str, Any],
) -> None:
    hero_logo, hero_text = st.columns([1, 4])
    with hero_logo:
        st.image(str(LOGO_FULL_PATH), width=150)
    with hero_text:
        st.title("Find your next obsession")
        st.write(
            "Search by title, author, genre or ISBN—or describe the exact kind of book you are in the mood for."
        )
        st.caption(
            f"Recommendations are personalised for {profile['display_name']} and improve as books are saved and rated."
        )

    _render_personalised_section(settings, db, api_key, profile)

    def set_quick_query(value: str) -> None:
        st.session_state.search_text = value
        st.session_state.trigger_search = True

    quick_cols = st.columns(4)
    for index, label in enumerate(QUICK_DISCOVERY):
        quick_cols[index % 4].button(
            label,
            key=f"quick_{label}",
            use_container_width=True,
            on_click=set_quick_query,
            args=(label,),
        )

    if "search_text" not in st.session_state:
        st.session_state.search_text = ""

    with st.form("search_form"):
        query = st.text_input(
            "Search",
            key="search_text",
            placeholder="e.g. fantasy with dragons, little romance, under 500 pages",
        )
        top1, top2, top3 = st.columns([1.2, 1, 1])
        with top1:
            search_style = st.selectbox("Search style", ("Smart description", "Exact catalogue fields"))
        with top2:
            mode = st.selectbox("Field", ("Keyword", "Title", "Author", "Genre / subject", "ISBN"))
        with top3:
            provider = st.selectbox("Catalogue", ("Auto", "Both", "Open Library", "Google Books"))

        with st.expander("Filters"):
            f1, f2, f3, f4 = st.columns(4)
            language_label = f1.selectbox("Language", tuple(LANGUAGES))
            order_label = f2.selectbox("Order", ("Most relevant", "Newest first"))
            result_count = f3.select_slider("Books per page", options=(12, 24, 36, 48), value=24)
            ebook_label = f4.selectbox("Availability", ("Any format", "Any eBook", "Free eBook", "Preview available"))
            p1, p2, p3, p4 = st.columns(4)
            min_rating = p1.slider("Minimum public rating", 0.0, 5.0, 0.0, 0.5)
            max_pages = p2.number_input("Maximum pages (0 = any)", min_value=0, max_value=5000, value=0, step=50)
            year_from = p3.number_input("Published from (0 = any)", min_value=0, max_value=2100, value=0, step=1)
            year_to = p4.number_input("Published by (0 = any)", min_value=0, max_value=2100, value=0, step=1)
        submitted = st.form_submit_button("Search books", type="primary", use_container_width=True)

    triggered = bool(st.session_state.pop("trigger_search", False))
    if submitted or triggered:
        st.session_state.search_request = {
            "query": query,
            "search_style": search_style,
            "mode": mode,
            "provider": provider,
            "result_count": int(result_count),
            "language_label": language_label,
            "order_label": order_label,
            "ebook_label": ebook_label,
            "min_rating": float(min_rating),
            "max_pages": int(max_pages),
            "year_from": int(year_from),
            "year_to": int(year_to),
        }
        _load_search_page(settings, api_key, 0)

    messages = st.session_state.get("search_messages", [])
    for message in messages:
        st.warning(message)
    if st.session_state.get("search_plan"):
        st.caption("Understood as: " + st.session_state.search_plan)

    results = [Book.from_dict(payload) for payload in st.session_state.get("search_results", [])]
    current_page = int(st.session_state.get("search_page", 0))
    if results:
        st.subheader(f"Search results · Page {current_page + 1}")
        render_book_grid(results, db, settings, api_key, context=f"search_page_{current_page}")
        previous, page_label, next_button = st.columns([1, 1.4, 1])
        if previous.button("← Previous page", disabled=current_page == 0, use_container_width=True):
            _load_search_page(settings, api_key, current_page - 1)
            st.rerun()
        page_label.markdown(
            f"<div style='text-align:center;padding-top:.6rem'><strong>Page {current_page + 1}</strong><br><span style='color:#9ca3af'>New catalogue results</span></div>",
            unsafe_allow_html=True,
        )
        if next_button.button("Next page →", use_container_width=True):
            _load_search_page(settings, api_key, current_page + 1)
            st.rerun()
    elif "search_results" in st.session_state:
        if current_page > 0:
            st.info("There are no more matching results on the next page.")
            if st.button("← Return to previous page", use_container_width=True):
                _load_search_page(settings, api_key, current_page - 1)
                st.rerun()
        else:
            st.info("No matching books survived the selected filters. Try broader wording or remove a filter.")
    else:
        st.info("Search both live catalogues above. Your personalised picks stay unchanged until you press Refresh from my library.")

    if st.session_state.get("show_similar_dialog") and st.session_state.get("similar_seed"):
        render_similar_dialog(db)
    if st.session_state.get("show_catalogue_detail_dialog") and st.session_state.get("catalogue_detail_book"):
        render_catalogue_book_dialog(db)


def _load_search_page(settings: Settings, api_key: str, page_index: int) -> None:
    request = st.session_state.get("search_request") or {}
    query = str(request.get("query") or "")
    search_style = str(request.get("search_style") or "Smart description")
    plan = parse_smart_query(query) if search_style == "Smart description" else SmartSearchPlan(query, query)
    api_query = plan.api_query if search_style == "Smart description" else query
    if not api_query.strip():
        st.warning("Enter something to search for.")
        return

    ebook_filter = {
        "Any format": "",
        "Any eBook": "ebooks",
        "Free eBook": "free-ebooks",
        "Preview available": "partial",
    }.get(str(request.get("ebook_label") or "Any format"), "")
    page_index = max(0, int(page_index))
    loader = st.empty()
    loader.markdown(
        _loader_html(
            "Finding your next obsession…",
            f"Loading catalogue page {page_index + 1} and ranking the best matches.",
        ),
        unsafe_allow_html=True,
    )
    try:
        payloads, messages = cached_search(
            api_query,
            str(request.get("mode") or "Keyword"),
            str(request.get("provider") or "Auto"),
            int(request.get("result_count") or 24),
            LANGUAGES.get(str(request.get("language_label") or "Any language"), ""),
            "newest" if request.get("order_label") == "Newest first" else "relevance",
            ebook_filter,
            api_key,
            settings.open_library_contact,
            settings.request_timeout_seconds,
            page_index,
        )
    finally:
        loader.empty()

    books = [Book.from_dict(payload) for payload in payloads]
    if search_style == "Smart description":
        books = rank_smart_results(books, plan)
    books = _filter_books(
        books,
        min_rating=float(request.get("min_rating") or 0.0),
        max_pages=int(request.get("max_pages") or 0),
        year_from=int(request.get("year_from") or 0),
        year_to=int(request.get("year_to") or 0),
        plan=plan,
    )
    st.session_state.search_results = [book.to_dict() for book in books]
    st.session_state.search_messages = messages
    st.session_state.search_plan = plan.explanation
    st.session_state.search_page = page_index
    st.session_state.similar_seed = None
    st.session_state.similar_results = []


def _render_personalised_section(
    settings: Settings,
    db: LibraryDatabase,
    api_key: str,
    profile: dict[str, Any],
) -> None:
    entries = db.list_entries("All")
    st.subheader("For You")
    if not entries:
        niches = profile.get("favourite_niches") or []
        st.info("Add at least one top book or save a book to start your personalised recommendations.")
        if niches:
            st.caption("Your starter taste: " + " · ".join(niches[:8]))
        return

    refresh_token = int(st.session_state.get("personalised_refresh_token", 0))
    payloads = st.session_state.get("personalised_results")
    needs_initial_build = payloads is None
    refresh_requested = bool(st.session_state.pop("personalised_refresh_requested", False))

    if needs_initial_build or refresh_requested:
        loader = st.empty()
        loader.markdown(
            _loader_html(
                "Searching from your exact favourite books…",
                f"Building fresh recommendations from {min(len(entries), 5)} saved books and your chosen niches.",
            ),
            unsafe_allow_html=True,
        )
        entry_payloads = [
            {
                "book": entry["book"].to_dict(),
                "shelf": entry.get("shelf"),
                "user_rating": entry.get("user_rating"),
                "updated_at": entry.get("updated_at"),
            }
            for entry in entries
        ]
        try:
            payloads, messages = cached_personalised(
                profile, entry_payloads, api_key, settings.open_library_contact,
                settings.request_timeout_seconds, 24,
                engine_version="v19.2-balanced-rich", refresh_token=refresh_token,
            )
        finally:
            loader.empty()
        st.session_state.personalised_results = payloads
        st.session_state.personalised_messages = messages
        st.session_state.personalised_display_offset = 0
        st.session_state.personalised_dirty = False

    for message in st.session_state.get("personalised_messages", []):
        st.caption(message)
    payloads = st.session_state.get("personalised_results", [])
    offset = max(0, int(st.session_state.get("personalised_display_offset", 0)))
    if offset >= len(payloads):
        offset = 0
        st.session_state.personalised_display_offset = 0
    visible_payloads = payloads[offset:offset + 6]
    books = [Book.from_dict(payload.get("book") or payload) for payload in visible_payloads]

    if st.session_state.get("personalised_dirty"):
        st.info("Your library changed. These recommendations stay in place until you press **Refresh from my library**.")

    if books:
        summary = taste_summary(profile, entries, 8)
        if summary:
            st.caption("Taste detected: " + " · ".join(summary))
        batch_number = (offset // 6) + 1
        total_batches = max(1, (len(payloads) + 5) // 6)
        st.caption(f"Recommendation set {refresh_token + 1} · batch {batch_number} of {total_batches}. Refreshing only changes the suggestions — it never saves a book.")
        render_book_grid(books, db, settings, api_key, context=f"personalised_{refresh_token}_{offset}")

        selection_scope = f"personalised_{refresh_token}_{offset}"
        selected_uids = {
            book.uid for book in books
            if st.session_state.get(f"select_{selection_scope}_{book.uid}", False)
        }

        st.markdown("#### Selected-book actions")
        count_col, batch_want, batch_read, batch_clear = st.columns([0.7, 1.4, 1.4, 1])
        count_col.metric("Selected", len(selected_uids))
        has_selection = bool(selected_uids)
        if batch_want.button(
            "Add selected to Want to Read",
            use_container_width=True,
            disabled=not has_selection,
            key=f"bulk_want_{selection_scope}",
        ):
            for book in books:
                if book.uid in selected_uids:
                    db.save_entry(book, "Want to Read")
            _invalidate_personalised_feed()
            _clear_personalised_selection()
            st.toast(f"Added {len(selected_uids)} books to Want to Read", icon="📚")
            st.rerun()
        if batch_read.button(
            "Mark selected as Read",
            use_container_width=True,
            disabled=not has_selection,
            key=f"bulk_read_{selection_scope}",
        ):
            for book in books:
                if book.uid in selected_uids:
                    db.save_entry(book, "Finished", progress_pages=int(book.page_count or 0))
            _invalidate_personalised_feed()
            _clear_personalised_selection()
            st.toast(f"Marked {len(selected_uids)} books as read", icon="✅")
            st.rerun()
        if batch_clear.button(
            "Clear selection",
            use_container_width=True,
            disabled=not has_selection,
            key=f"bulk_clear_{selection_scope}",
        ):
            _clear_personalised_selection()
            st.rerun()

        if not has_selection:
            st.caption("Tick **Select** on one or more recommendations, then use the buttons above.")

        nav1, nav2 = st.columns(2)
        if nav1.button("Next recommendation batch", use_container_width=True, disabled=total_batches <= 1):
            st.session_state.personalised_display_offset = (offset + 6) % max(len(payloads), 1)
            st.rerun()
        if nav2.button("Refresh from my library", type="primary", use_container_width=True):
            st.session_state.personalised_refresh_token = refresh_token + 1
            st.session_state.personalised_refresh_requested = True
            st.session_state.personalised_display_offset = 0
            _clear_personalised_selection()
            st.rerun()
    else:
        st.warning("The live catalogues returned no new books this time.")
        if st.button("Refresh from my library", type="primary", use_container_width=True):
            st.session_state.personalised_refresh_token = refresh_token + 1
            st.session_state.personalised_refresh_requested = True
            st.rerun()


def render_book_grid(
    books: list[Book],
    db: LibraryDatabase,
    settings: Settings,
    api_key: str,
    context: str,
) -> None:
    for row_start in range(0, len(books), 3):
        columns = st.columns(3)
        for offset, book in enumerate(books[row_start : row_start + 3]):
            with columns[offset]:
                render_book_card(book, db, settings, api_key, f"{context}_{row_start + offset}")


def render_book_card(
    book: Book,
    db: LibraryDatabase,
    settings: Settings,
    api_key: str,
    key_prefix: str,
) -> None:
    with st.container(border=True):
        if key_prefix.startswith("personalised_"):
            selection_scope = _personalised_selection_scope(key_prefix)
            st.checkbox(
                "Select", key=f"select_{selection_scope}_{book.uid}",
                help="Select several recommendations, then add them together below.",
            )
        image_col, text_col = st.columns([0.34, 0.66])
        with image_col:
            if book.best_cover:
                st.image(book.best_cover, width=140)
            else:
                st.markdown("### 📕")
                st.caption("No cover")
        with text_col:
            st.markdown(f'<div class="book-title">{_escape(book.display_title)}</div>', unsafe_allow_html=True)
            st.caption(book.author_text)
            meta = []
            if book.published_year:
                meta.append(str(book.published_year))
            if book.page_count:
                meta.append(f"{book.page_count:,} pages")
            if book.average_rating is not None:
                meta.append(f"★ {book.average_rating:.1f} ({book.ratings_count:,})")
            st.markdown(
                f'<div class="book-meta">{" · ".join(meta) or "Metadata varies by edition"}</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<span class="source-pill">{_escape(book.source)}</span>', unsafe_allow_html=True
            )

        if book.categories:
            st.caption(" • ".join(book.categories[:4]))

        # Keep the synopsis visible on every search/recommendation card.  Earlier
        # versions removed it behind the details button, which made browsing much
        # less useful.  The full text remains available in the internal dialog.
        if book.description:
            st.markdown("**Description**")
            st.write(_description_preview(book.description, 650))
            if len(book.description.strip()) > 650:
                with st.expander("Read the full description"):
                    st.write(book.description)
        else:
            st.caption(
                "No synopsis is available for this catalogue edition. "
                "BookVerse will still try both catalogues when full details are opened."
            )

        if st.button(
            "View full details",
            key=f"details_{key_prefix}_{book.uid}",
            use_container_width=True,
        ):
            loader = st.empty()
            loader.markdown(
                _loader_html(
                    "Loading full book details…",
                    f"Finding the exact {book.display_title} record and its full synopsis.",
                ),
                unsafe_allow_html=True,
            )
            try:
                enriched_payload = cached_enrich_catalogue_book(
                    book.to_dict(),
                    api_key,
                    settings.open_library_contact,
                    settings.request_timeout_seconds,
                )
            finally:
                loader.empty()
            st.session_state.catalogue_detail_book = enriched_payload
            st.session_state.show_catalogue_detail_dialog = True
            st.rerun()

        existing = next((entry for entry in db.list_entries("All") if entry["uid"] == book.uid), None)
        quick_want, quick_read = st.columns(2)
        if quick_want.button(
            "Want to Read",
            key=f"want_{key_prefix}_{book.uid}",
            use_container_width=True,
            disabled=bool(existing and existing["shelf"] == "Want to Read"),
        ):
            db.save_entry(book, "Want to Read")
            _invalidate_personalised_feed()
            st.toast(f"Added {book.display_title} to Want to Read", icon="📚")
            st.rerun()
        if quick_read.button(
            "✓ Mark as Read",
            key=f"read_{key_prefix}_{book.uid}",
            use_container_width=True,
            disabled=bool(existing and existing["shelf"] == "Finished"),
        ):
            db.save_entry(book, "Finished", progress_pages=int(book.page_count or 0))
            _invalidate_personalised_feed()
            st.toast(f"Marked {book.display_title} as read", icon="✅")
            st.rerun()

        if existing:
            display_shelf = "Read" if existing["shelf"] == "Finished" else existing["shelf"]
            st.caption(f"Currently in your library: **{display_shelf}**")

        with st.expander("More library options"):
            known_shelves = db.shelves()
            existing_shelf = existing["shelf"] if existing else "Want to Read"
            shelf_index = known_shelves.index(existing_shelf) if existing_shelf in known_shelves else 0
            shelf = st.selectbox(
                "Shelf", known_shelves, index=shelf_index, key=f"shelf_{key_prefix}_{book.uid}"
            )
            custom_shelf = st.text_input(
                "Or custom shelf",
                key=f"custom_shelf_{key_prefix}_{book.uid}",
                placeholder="e.g. Autumn horror",
            )
            rating = st.slider(
                "Your rating (0 = unrated)", 0.0, 5.0,
                float(existing["user_rating"] or 0.0) if existing else 0.0, 0.5,
                key=f"rating_{key_prefix}_{book.uid}",
            )
            progress = st.number_input(
                "Pages read", min_value=0, max_value=max(book.page_count or 10000, 10000),
                value=int(existing["progress_pages"] or 0) if existing else 0,
                key=f"progress_{key_prefix}_{book.uid}",
            )
            if st.button("Save library changes", key=f"save_{key_prefix}_{book.uid}", use_container_width=True):
                db.save_entry(
                    book,
                    custom_shelf.strip() or shelf,
                    user_rating=rating or None,
                    progress_pages=int(progress),
                )
                _invalidate_personalised_feed()
                st.toast(f"Saved {book.display_title}", icon="📚")
                st.rerun()

        if st.button("Find similar books", key=f"similar_{key_prefix}_{book.uid}", use_container_width=True):
            loader = st.empty()
            loader.markdown(_loader_html("Finding similar books…", "Building a recommendation set from both catalogues."), unsafe_allow_html=True)
            try:
                payloads, messages = cached_similar(
                    book.to_dict(),
                    api_key,
                    settings.open_library_contact,
                    settings.request_timeout_seconds,
                    24,
                )
            finally:
                loader.empty()
            st.session_state.similar_seed = book.to_dict()
            st.session_state.similar_results = payloads
            st.session_state.similar_messages = messages
            st.session_state.similar_index = 0
            st.session_state.similar_min_public_rating = 0.0
            st.session_state.show_similar_dialog = True
            st.rerun()


@st.dialog("Book details", width="large")
def render_catalogue_book_dialog(db: LibraryDatabase) -> None:
    payload = st.session_state.get("catalogue_detail_book")
    if not payload:
        st.info("No book is selected.")
        return
    book = Book.from_dict(payload)
    _render_internal_book_information(book)

    existing = next((entry for entry in db.list_entries("All") if entry["uid"] == book.uid), None)
    st.divider()
    want, read, close = st.columns(3)
    if want.button(
        "Want to Read",
        use_container_width=True,
        disabled=bool(existing and existing["shelf"] == "Want to Read"),
        key=f"detail_want_{book.uid}",
    ):
        db.save_entry(book, "Want to Read")
        _invalidate_personalised_feed()
        st.toast(f"Added {book.display_title} to Want to Read", icon="📚")
        st.rerun()
    if read.button(
        "✓ Mark as Read",
        use_container_width=True,
        disabled=bool(existing and existing["shelf"] == "Finished"),
        key=f"detail_read_{book.uid}",
    ):
        db.save_entry(book, "Finished", progress_pages=int(book.page_count or 0))
        _invalidate_personalised_feed()
        st.toast(f"Marked {book.display_title} as read", icon="✅")
        st.rerun()
    if close.button("Close", use_container_width=True, key=f"detail_close_{book.uid}"):
        st.session_state.show_catalogue_detail_dialog = False
        st.session_state.pop("catalogue_detail_book", None)
        st.rerun()


@st.dialog("Recommended books", width="large")
def render_similar_dialog(db: LibraryDatabase) -> None:
    seed_payload = st.session_state.get("similar_seed")
    payloads = st.session_state.get("similar_results", [])
    if not seed_payload:
        st.info("Choose a book first.")
        return

    seed = Book.from_dict(seed_payload)
    recommendations = []
    for payload in payloads:
        if "book" in payload:
            recommendations.append({
                "book": Book.from_dict(payload["book"]),
                "score": float(payload.get("score", 0.0)),
                "match_percent": int(payload.get("match_percent", 0)),
                "match_label": str(payload.get("match_label") or "Recommendation match"),
                "reasons": tuple(payload.get("reasons") or ()),
            })
        else:
            recommendations.append({
                "book": Book.from_dict(payload),
                "score": 0.0,
                "match_percent": 0,
                "match_label": "Recommendation match",
                "reasons": (),
            })

    st.caption(f"Because you selected **{seed.display_title}** by {seed.author_text}")
    st.caption("Recommendations are limited to English-language catalogue records and descriptions.")
    seed_dna = profile_summary(seed)
    if seed_dna:
        st.caption("Selected book DNA: " + " · ".join(seed_dna))

    for message in st.session_state.get("similar_messages", []):
        st.warning(message)

    filter_col, count_col = st.columns([1.25, 1])
    with filter_col:
        minimum_public_rating = st.slider(
            "Minimum public rating",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            key="similar_min_public_rating",
            help=(
                "Set this above 0 to show only recommendations with a public rating at or above "
                "your chosen score. Unrated books are hidden when a minimum is selected."
            ),
        )

    all_recommendation_count = len(recommendations)
    if minimum_public_rating > 0:
        recommendations = [
            recommendation
            for recommendation in recommendations
            if recommendation["book"].average_rating is not None
            and recommendation["book"].average_rating >= minimum_public_rating
        ]

    with count_col:
        if minimum_public_rating > 0:
            st.metric(
                "Recommendations shown",
                len(recommendations),
                delta=f"of {all_recommendation_count} total",
                delta_color="off",
            )
        else:
            rated_count = sum(
                recommendation["book"].average_rating is not None
                for recommendation in recommendations
            )
            st.metric(
                "Recommendations shown",
                len(recommendations),
                delta=f"{rated_count} have ratings",
                delta_color="off",
            )

    if not recommendations:
        if all_recommendation_count and minimum_public_rating > 0:
            st.warning(
                f"No recommendations have a public rating of {minimum_public_rating:.1f}★ or above. "
                "Lower the minimum rating to see more books."
            )
        else:
            st.warning(
                "No defensible matches were found from the live catalogues. The app rejected weak "
                "genre-only matches instead of filling the list with unrelated books."
            )
        if st.button("Close", use_container_width=True, key=f"similar_close_empty_{seed.uid}"):
            st.session_state.show_similar_dialog = False
            st.rerun()
        return

    index = min(max(int(st.session_state.get("similar_index", 0)), 0), len(recommendations) - 1)
    st.session_state.similar_index = index
    recommendation = recommendations[index]
    book = recommendation["book"]

    # Navigation is intentionally separated from the save form. Clicking Previous/Next
    # can only change the recommendation index and cannot write to the library.
    nav_previous, nav_status, nav_next = st.columns([1, 2, 1])
    if nav_previous.button(
        "← Previous",
        disabled=index == 0,
        use_container_width=True,
        key=f"similar_previous_{seed.uid}_{index}",
    ):
        st.session_state.similar_index = index - 1
        st.rerun()
    nav_status.markdown(
        f"<div style='text-align:center;padding-top:.55rem'><strong>Recommendation {index + 1} of {len(recommendations)}</strong></div>",
        unsafe_allow_html=True,
    )
    if nav_next.button(
        "Next →",
        disabled=index >= len(recommendations) - 1,
        use_container_width=True,
        key=f"similar_next_{seed.uid}_{index}",
    ):
        st.session_state.similar_index = index + 1
        st.rerun()

    st.progress((index + 1) / len(recommendations))

    cover_col, detail_col = st.columns([0.32, 0.68])
    with cover_col:
        if book.best_cover:
            st.image(book.best_cover, width=140)
        else:
            st.markdown("# 📕")
            st.caption("No cover available")
    with detail_col:
        st.subheader(book.display_title)
        st.write(f"**{book.author_text}**")
        meta: list[str] = []
        if book.published_year:
            meta.append(str(book.published_year))
        if book.page_count:
            meta.append(f"{book.page_count:,} pages")
        if meta:
            st.caption(" · ".join(meta))

        if book.average_rating is not None:
            rating_count_text = (
                f" from {book.ratings_count:,} public ratings"
                if book.ratings_count
                else ""
            )
            st.markdown(
                f"**Public book rating: ★ {book.average_rating:.1f}/5{rating_count_text}**"
            )
        else:
            st.caption("Public book rating: Not available from the connected catalogues")

        if book.categories:
            st.caption(" • ".join(book.categories[:6]))
        reasons = recommendation.get("reasons") or ()
        match_percent = int(recommendation.get("match_percent") or 0)
        match_label = str(recommendation.get("match_label") or "Recommendation match")
        if match_percent:
            st.markdown(f"**{match_label} · {match_percent}%**")
        if reasons:
            st.success("Why it matches: " + " · ".join(reasons))
        if book.description:
            st.write(book.description[:1400] + ("…" if len(book.description) > 1400 else ""))
        else:
            st.info("This catalogue entry has no description, but it matched the selected book's metadata.")

        st.caption("The description and available catalogue details are shown inside BookVerse.")

    saved_entries = {entry["uid"]: entry for entry in db.list_entries("All")}
    existing = saved_entries.get(book.uid)

    st.divider()
    quick_want, quick_read = st.columns(2)
    if quick_want.button(
        "Want to Read",
        use_container_width=True,
        disabled=bool(existing and existing["shelf"] == "Want to Read"),
        key=f"recommendation_want_{seed.uid}_{book.uid}_{index}",
    ):
        db.save_entry(book, "Want to Read")
        _invalidate_personalised_feed()
        st.toast(f"Added {book.display_title} to Want to Read", icon="📚")
        st.rerun()
    if quick_read.button(
        "✓ Mark as Read",
        use_container_width=True,
        disabled=bool(existing and existing["shelf"] == "Finished"),
        key=f"recommendation_read_{seed.uid}_{book.uid}_{index}",
    ):
        db.save_entry(book, "Finished", progress_pages=int(book.page_count or 0))
        _invalidate_personalised_feed()
        st.toast(f"Marked {book.display_title} as read", icon="✅")
        st.rerun()

    with st.expander(
        "More library options" if not existing else f"More options · currently on {existing['shelf']}",
        expanded=False,
    ):
        st.caption(
            "Previous, Next and Refresh never save books. Only Want to Read, Mark as Read, or submitting this form changes your library."
        )
        shelves = db.shelves()
        existing_shelf = existing["shelf"] if existing else "Want to Read"
        shelf_index = shelves.index(existing_shelf) if existing_shelf in shelves else 0
        existing_rating = float(existing["user_rating"] or 0.0) if existing else 0.0
        existing_progress = int(existing["progress_pages"] or 0) if existing else 0

        with st.form(
            key=f"recommendation_save_form_{seed.uid}_{book.uid}_{index}",
            clear_on_submit=False,
        ):
            save1, save2, save3 = st.columns([1.2, 1, 1])
            shelf = save1.selectbox(
                "Save to shelf",
                shelves,
                index=shelf_index,
                key=f"dialog_shelf_{book.uid}_{index}",
            )
            rating = save2.slider(
                "Your rating",
                0.0,
                5.0,
                existing_rating,
                0.5,
                key=f"dialog_rating_{book.uid}_{index}",
            )
            progress = save3.number_input(
                "Pages read",
                min_value=0,
                max_value=max(book.page_count or 10000, 10000),
                value=existing_progress,
                key=f"dialog_progress_{book.uid}_{index}",
            )
            custom_shelf = st.text_input(
                "Custom shelf (optional)",
                key=f"dialog_custom_{book.uid}_{index}",
                placeholder="e.g. Dark fantasy shortlist",
            )
            save_submitted = st.form_submit_button(
                "Update saved book" if existing else "Save this book",
                type="primary",
                use_container_width=True,
            )

        if save_submitted:
            db.save_entry(
                book,
                custom_shelf.strip() or shelf,
                user_rating=rating or None,
                progress_pages=int(progress),
            )
            _invalidate_personalised_feed()
            st.success(f"Saved **{book.display_title}**.")

        if existing:
            if st.button(
                "Remove this book from my library",
                key=f"remove_saved_recommendation_{book.uid}_{index}",
                use_container_width=True,
            ):
                db.remove_entry(book.uid)
                _invalidate_personalised_feed()
                st.success(f"Removed **{book.display_title}** from your library.")
                st.rerun()

    if st.button("Close recommendations", use_container_width=True, key=f"similar_close_{seed.uid}_{index}"):
        st.session_state.show_similar_dialog = False
        st.rerun()


def render_library(db: LibraryDatabase) -> None:
    st.title("My Library")
    st.caption(
        "Click a book spine to open it inside this BookVerse session. "
        "No new page is loaded, so your unlocked profile stays active."
    )

    entries_all = db.list_entries("All")
    shelves = ["All", *db.shelves()]
    control1, control2, control3 = st.columns([1, 2, 1])
    shelf = control1.selectbox("Shelf", shelves)
    local_query = control2.text_input("Filter your bookcase", placeholder="Title, author or category")
    sort_mode = control3.selectbox("Arrange by", ("Recently saved", "Title", "Author", "Book height"))

    entries = db.list_entries(shelf)
    if local_query.strip():
        needle = local_query.casefold().strip()
        entries = [
            entry for entry in entries
            if needle in " ".join(
                [entry["book"].title, entry["book"].author_text, entry["book"].category_text]
            ).casefold()
        ]

    if sort_mode == "Title":
        entries.sort(key=lambda item: item["book"].title.casefold())
    elif sort_mode == "Author":
        entries.sort(key=lambda item: item["book"].author_text.casefold())
    elif sort_mode == "Book height":
        entries.sort(key=lambda item: item["book"].page_count or 0, reverse=True)

    m1, m2, m3 = st.columns(3)
    m1.metric("Books saved", len(entries_all))
    m2.metric("Currently reading", sum(entry["shelf"] == "Reading" for entry in entries_all))
    m3.metric("Read", sum(entry["shelf"] == "Finished" for entry in entries_all))

    with st.expander("Backup, restore and export"):
        backup = json.dumps(db.backup_payload(), indent=2, ensure_ascii=False)
        st.download_button(
            "Download full backup (JSON)", backup, file_name="bookverse_backup.json", mime="application/json"
        )
        csv_data = _entries_dataframe(entries_all).to_csv(index=False)
        st.download_button(
            "Download readable library (CSV)", csv_data, file_name="bookverse_library.csv", mime="text/csv"
        )
        upload = st.file_uploader("Restore a BookVerse JSON backup", type=("json",))
        if upload is not None and st.button("Restore backup"):
            try:
                count = db.restore_payload(json.load(upload))
                st.success(f"Restored {count} library entries.")
                st.rerun()
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                st.error(f"Could not restore backup: {exc}")

    if not entries:
        st.markdown(
            '<div class="bookcase-frame"><div class="bookcase-nameplate">BookVerse Library</div>'
            '<div class="bookcase-empty-space">This shelf is waiting for its first book.</div>'
            '<div class="bookcase-row"></div></div>',
            unsafe_allow_html=True,
        )
        return

    grouped: dict[str, list[dict[str, Any]]] = {}
    if shelf == "All":
        for entry in entries:
            grouped.setdefault(str(entry["shelf"]), []).append(entry)
    else:
        grouped[shelf] = entries

    # Every spine is a real Streamlit button. Unlike the older query-string links,
    # these callbacks remain on the same websocket/session and therefore preserve
    # the unlocked profile.
    spine_css: list[str] = []
    for entry in entries:
        book: Book = entry["book"]
        spine, spine_dark = _spine_colours(book.uid)
        page_count = book.page_count or 320
        height = max(142, min(198, 142 + int(min(page_count, 900) / 900 * 56)))
        key_suffix = hashlib.sha256(str(entry["uid"]).encode("utf-8")).hexdigest()[:12]
        spine_css.append(
            f"""
            .st-key-spine_{key_suffix} {{
                min-height: 208px; display: flex; align-items: flex-end;
            }}
            .st-key-spine_{key_suffix} button {{
                height: {height}px; min-height: {height}px; width: 100%; padding: 9px 5px;
                border: 1px solid rgba(255,255,255,.22); border-radius: 5px 5px 2px 2px;
                background: linear-gradient(90deg, {spine_dark} 0%, {spine} 16%, {spine} 82%, {spine_dark} 100%);
                color: #fff8df; text-shadow: 0 1px 2px rgba(0,0,0,.9);
                box-shadow: inset 2px 0 rgba(255,255,255,.13), inset -2px 0 rgba(0,0,0,.34), 2px 2px 5px rgba(0,0,0,.58);
                transition: transform .16s ease, filter .16s ease; overflow: hidden;
            }}
            .st-key-spine_{key_suffix} button:hover {{
                transform: translateY(-9px) rotate(-1deg); filter: brightness(1.16);
                border-color: #e2ad57;
            }}
            .st-key-spine_{key_suffix} button p {{
                writing-mode: vertical-rl; transform: rotate(180deg); white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; max-height: {height - 24}px;
                margin: auto; font-size: .78rem; font-weight: 750; letter-spacing: .015em;
            }}
            """
        )

    st.markdown(
        """
        <style>
        .st-key-live_bookcase_frame {
            padding: 1rem 1rem .5rem; border: 10px solid #5b321c; border-radius: .8rem;
            background: radial-gradient(circle at 50% 5%, #3b2619 0%, #21140e 72%);
            box-shadow: inset 0 0 0 3px #9a6035, inset 0 0 32px rgba(0,0,0,.72);
            margin: .8rem 0 1.3rem;
        }
        [class*="st-key-live_shelf_row_"] {
            position: relative; min-height: 230px; padding: 8px 14px 24px;
            border-bottom: 18px solid #65371f;
            box-shadow: inset 0 -3px #c07b42, 0 8px 12px rgba(0,0,0,.62);
            margin-bottom: 14px;
        }
        .live-shelf-heading {
            color: #f5deb3; background: #4a2817; border: 1px solid #bb7a41;
            border-radius: .3rem; padding: .25rem .7rem; width: fit-content;
            font-size: .82rem; font-weight: 750; margin: .2rem 0 .35rem;
        }
        </style>
        """ + "<style>" + "".join(spine_css) + "</style>",
        unsafe_allow_html=True,
    )

    selected_uid: str | None = None
    with st.container(key="live_bookcase_frame"):
        st.markdown('<div class="bookcase-nameplate">BookVerse Library</div>', unsafe_allow_html=True)
        for shelf_index, (shelf_name, shelf_entries) in enumerate(grouped.items()):
            display_shelf_name = "Read" if shelf_name == "Finished" else shelf_name
            shelf_hash = hashlib.sha256(str(shelf_name).encode("utf-8")).hexdigest()[:10]
            page_key = f"bookcase_page_{shelf_hash}"
            page_size = 15
            page_count = max(1, (len(shelf_entries) + page_size - 1) // page_size)
            current_page = max(0, min(int(st.session_state.get(page_key, 0)), page_count - 1))
            st.session_state[page_key] = current_page
            page_start = current_page * page_size
            page_entries = shelf_entries[page_start:page_start + page_size]
            page_end = page_start + len(page_entries)

            heading_left, heading_right = st.columns([3, 1])
            with heading_left:
                st.markdown(
                    f'<div class="live-shelf-heading">{_escape(display_shelf_name)}</div>',
                    unsafe_allow_html=True,
                )
            with heading_right:
                st.caption(f"Books {page_start + 1}–{page_end} of {len(shelf_entries)}")

            row_key = hashlib.sha256(
                f"{shelf_name}:{shelf_index}:{current_page}".encode("utf-8")
            ).hexdigest()[:10]
            with st.container(key=f"live_shelf_row_{row_key}"):
                columns = st.columns(page_size, gap="small", vertical_alignment="bottom")
                for column, entry in zip(columns, page_entries):
                    book: Book = entry["book"]
                    key_suffix = hashlib.sha256(str(entry["uid"]).encode("utf-8")).hexdigest()[:12]
                    tooltip = f"{book.display_title} — {book.author_text} | {display_shelf_name}"
                    with column:
                        if st.button(
                            book.display_title,
                            key=f"spine_{key_suffix}",
                            help=tooltip,
                            use_container_width=True,
                            type="tertiary",
                        ):
                            selected_uid = str(entry["uid"])

            previous_col, page_col, next_col = st.columns([1, 1.2, 1])
            if previous_col.button(
                "← Previous 15",
                key=f"bookcase_previous_{shelf_hash}",
                use_container_width=True,
                disabled=current_page == 0,
            ):
                st.session_state[page_key] = current_page - 1
                st.rerun()
            page_col.markdown(
                f"<div style='text-align:center;padding:.55rem 0;color:#d8c4a5;'>Shelf page {current_page + 1} of {page_count}</div>",
                unsafe_allow_html=True,
            )
            if next_col.button(
                "Next 15 →",
                key=f"bookcase_next_{shelf_hash}",
                use_container_width=True,
                disabled=current_page >= page_count - 1,
            ):
                st.session_state[page_key] = current_page + 1
                st.rerun()

    if selected_uid is not None:
        st.session_state.library_selected_uid = selected_uid

    active_uid = st.session_state.get("library_selected_uid")
    if active_uid:
        selected = next((entry for entry in entries_all if str(entry["uid"]) == str(active_uid)), None)
        if selected:
            render_bookcase_book_dialog(db, selected)
        else:
            st.session_state.pop("library_selected_uid", None)

    st.caption(
        "Hover over a spine to lift it from the shelf. Clicking a spine opens its full details "
        "inside this active BookVerse session."
    )


@st.dialog("Book details", width="large")
def render_bookcase_book_dialog(db: LibraryDatabase, entry: dict[str, Any]) -> None:
    book: Book = entry["book"]
    settings = get_settings()
    if not book.description or len(book.description) < 100 or not book.categories:
        with st.spinner("Loading the richest available book information…"):
            enriched_payload = cached_enrich_library_book(
                book.to_dict(), settings.google_books_api_key,
                settings.open_library_contact, settings.request_timeout_seconds,
            )
        enriched_book = Book.from_dict(enriched_payload)
        if enriched_book.to_dict() != book.to_dict():
            db.save_entry(
                enriched_book, entry["shelf"], user_rating=entry.get("user_rating"),
                review=entry.get("review") or "", progress_pages=int(entry.get("progress_pages") or 0),
            )
            book = enriched_book
    _render_internal_book_information(book)

    display_shelf = "Read" if entry["shelf"] == "Finished" else entry["shelf"]
    st.info(f"This book is currently on your **{display_shelf}** shelf.")
    if entry.get("user_rating") is not None:
        st.write(f"**Your rating:** ★ {float(entry['user_rating']):.1f}/5")
    if book.page_count:
        progress_pages = int(entry.get("progress_pages") or 0)
        st.progress(
            min(progress_pages / max(book.page_count, 1), 1.0),
            text=f"{progress_pages:,} / {book.page_count:,} pages read",
        )
    if entry.get("review"):
        st.subheader("Your review / notes")
        st.write(entry["review"])

    st.divider()
    quick_want, quick_read, quick_reading = st.columns(3)
    if quick_want.button(
        "Want to Read",
        use_container_width=True,
        disabled=entry["shelf"] == "Want to Read",
        key=f"case_quick_want_{entry['uid']}",
    ):
        db.update_entry(entry["uid"], "Want to Read", entry.get("user_rating"), entry.get("review") or "", 0)
        _invalidate_personalised_feed()
        st.toast("Moved to Want to Read", icon="📚")
        st.rerun()
    if quick_read.button(
        "✓ Mark as Read",
        use_container_width=True,
        disabled=entry["shelf"] == "Finished",
        key=f"case_quick_read_{entry['uid']}",
    ):
        db.update_entry(
            entry["uid"], "Finished", entry.get("user_rating"), entry.get("review") or "",
            int(book.page_count or entry.get("progress_pages") or 0),
        )
        _invalidate_personalised_feed()
        st.toast("Marked as read", icon="✅")
        st.rerun()
    if quick_reading.button(
        "Currently Reading",
        use_container_width=True,
        disabled=entry["shelf"] == "Reading",
        key=f"case_quick_reading_{entry['uid']}",
    ):
        db.update_entry(entry["uid"], "Reading", entry.get("user_rating"), entry.get("review") or "", int(entry.get("progress_pages") or 0))
        _invalidate_personalised_feed()
        st.toast("Moved to Currently Reading", icon="📖")
        st.rerun()

    st.subheader("Edit reading record")
    with st.form(key=f"bookcase_edit_form_{entry['uid']}"):
        edit1, edit2 = st.columns(2)
        shelf_options = db.shelves()
        current_index = shelf_options.index(entry["shelf"]) if entry["shelf"] in shelf_options else 0
        new_shelf = edit1.selectbox("Shelf", shelf_options, index=current_index)
        custom_shelf = edit2.text_input("Custom shelf", placeholder="Optional")
        current_rating = float(entry.get("user_rating") or 0.0)
        new_rating = st.slider("Your rating", 0.0, 5.0, current_rating, 0.5)
        new_progress = st.number_input(
            "Pages read", min_value=0, max_value=max(book.page_count or 10000, 10000),
            value=int(entry.get("progress_pages") or 0),
        )
        new_review = st.text_area("Review / notes", value=entry.get("review") or "")
        save_changes = st.form_submit_button("Save changes", type="primary", use_container_width=True)
    if save_changes:
        db.update_entry(
            entry["uid"], custom_shelf.strip() or new_shelf, new_rating or None, new_review, int(new_progress)
        )
        _invalidate_personalised_feed()
        st.session_state.pop("library_selected_uid", None)
        st.toast("Bookcase updated", icon="📚")
        st.rerun()

    remove, close = st.columns(2)
    if remove.button("Remove book", use_container_width=True, key=f"case_remove_{entry['uid']}"):
        db.remove_entry(entry["uid"])
        _invalidate_personalised_feed()
        st.session_state.pop("library_selected_uid", None)
        st.toast("Book removed from the shelf", icon="🗑️")
        st.rerun()
    if close.button("Close", use_container_width=True, key=f"case_close_{entry['uid']}"):
        st.session_state.pop("library_selected_uid", None)
        st.rerun()



def _description_preview(description: str, limit: int = 650) -> str:
    """Return a readable synopsis preview without chopping through a word."""
    value = " ".join(str(description or "").split())
    if len(value) <= limit:
        return value
    shortened = value[: max(0, limit - 1)].rsplit(" ", 1)[0].rstrip(" ,.;:")
    return shortened + "…"



def _render_internal_book_information(book: Book) -> None:
    """Show the richest available catalogue record without leaving BookVerse."""
    cover, details = st.columns([0.28, 0.72])
    with cover:
        if book.best_cover:
            st.image(book.best_cover, use_container_width=True)
        else:
            st.markdown("# 📕")
            st.caption("No cover available")
    with details:
        st.title(book.display_title)
        st.subheader(book.author_text)
        metadata: list[str] = []
        if book.published_date:
            metadata.append(book.published_date)
        if book.page_count:
            metadata.append(f"{book.page_count:,} pages")
        if book.average_rating is not None:
            rating_text = f"★ {book.average_rating:.1f}/5"
            if book.ratings_count:
                rating_text += f" from {book.ratings_count:,} public ratings"
            metadata.append(rating_text)
        st.caption(" · ".join(metadata) or "Metadata varies by edition")

        if book.categories:
            st.write("**Genres and subjects:** " + " · ".join(book.categories[:12]))
        if book.description:
            st.subheader("Description")
            st.write(book.description)
        else:
            st.info("No description is available for this catalogue edition.")

    st.subheader("Catalogue information")
    info_rows: list[tuple[str, str]] = []
    if book.publisher:
        info_rows.append(("Publisher", book.publisher))
    if book.language:
        info_rows.append(("Language", book.language))
    if book.isbn13:
        info_rows.append(("ISBN-13", book.isbn13))
    if book.isbn10:
        info_rows.append(("ISBN-10", book.isbn10))
    info_rows.append(("Catalogue source", "Google Books" if book.source == "google" else "Open Library"))
    info_rows.append(("eBook listed", "Yes" if book.is_ebook or book.ebook_available else "No / not confirmed"))
    info_rows.append(("Public domain", "Yes" if book.public_domain else "No / not confirmed"))
    left, right = st.columns(2)
    for index, (label, value) in enumerate(info_rows):
        target = left if index % 2 == 0 else right
        target.markdown(f"**{label}:** {_escape(str(value))}")


def _personalised_selection_scope(key_prefix: str) -> str:
    """Return the stable selection scope for a personalised recommendation batch.

    Card prefixes also contain a grid-position suffix. Bulk actions must ignore
    that suffix so their keys exactly match the checkboxes rendered on cards.
    """
    parts = str(key_prefix).split("_")
    if len(parts) >= 3 and parts[0] == "personalised":
        return "_".join(parts[:3])
    return str(key_prefix)


def _invalidate_personalised_feed() -> None:
    """Mark the current recommendations as stale without rebuilding them automatically."""
    st.session_state.personalised_dirty = True


def _clear_personalised_selection() -> None:
    for key in list(st.session_state):
        if str(key).startswith("select_personalised_"):
            st.session_state.pop(key, None)



def _spine_colours(uid: str) -> tuple[str, str]:
    palettes = (
        ("#244e75", "#10283d"), ("#7b2f35", "#3d161a"), ("#356444", "#183421"),
        ("#704d8c", "#342341"), ("#a0602d", "#503017"), ("#8a7a2f", "#443c16"),
        ("#365d62", "#183033"), ("#9a3d62", "#4d1d31"), ("#5e4937", "#30251c"),
        ("#31558f", "#172947"), ("#6e384f", "#351b26"), ("#446b2e", "#203517"),
    )
    digest = hashlib.sha256(str(uid).encode("utf-8")).digest()
    return palettes[digest[0] % len(palettes)]


def render_stats(db: LibraryDatabase) -> None:
    st.title("Reading Stats")
    entries = db.list_entries("All")
    if not entries:
        st.info("Save and finish some books to build your reading dashboard.")
        return

    finished = [entry for entry in entries if entry["shelf"] == "Finished"]
    rated = [entry for entry in entries if entry["user_rating"] is not None]
    pages_finished = sum(entry["book"].page_count or 0 for entry in finished)
    average_rating = sum(float(entry["user_rating"]) for entry in rated) / len(rated) if rated else 0.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saved", len(entries))
    c2.metric("Finished", len(finished))
    c3.metric("Pages finished", f"{pages_finished:,}")
    c4.metric("Your average rating", f"{average_rating:.1f}" if rated else "—")

    current_year = datetime.now().year
    existing_goal = int(db.get_setting("annual_book_goal", "24") or 24)
    goal = st.number_input("Annual book goal", min_value=1, max_value=1000, value=existing_goal)
    if int(goal) != existing_goal:
        db.set_setting("annual_book_goal", str(int(goal)))
    finished_this_year = sum(
        1 for entry in finished if (entry["finished_at"] or "").startswith(str(current_year))
    )
    st.progress(
        min(finished_this_year / max(int(goal), 1), 1.0),
        text=f"{finished_this_year} of {int(goal)} books finished in {current_year}",
    )

    st.subheader("Books by shelf")
    shelf_counts = pd.Series([entry["shelf"] for entry in entries]).value_counts().rename("Books")
    st.bar_chart(shelf_counts)

    categories = favourite_categories([entry["book"] for entry in entries], limit=10)
    if categories:
        st.subheader("Most common categories")
        category_df = pd.DataFrame(categories, columns=("Category", "Books")).set_index("Category")
        st.bar_chart(category_df)

    monthly_counts: dict[str, int] = {}
    for entry in finished:
        finished_at = entry["finished_at"] or ""
        if len(finished_at) >= 7:
            key = finished_at[:7]
            monthly_counts[key] = monthly_counts.get(key, 0) + 1
    if monthly_counts:
        st.subheader("Finishes by month")
        monthly_df = pd.DataFrame(
            sorted(monthly_counts.items()), columns=("Month", "Books")
        ).set_index("Month")
        st.line_chart(monthly_df)


def render_settings_about(
    settings: Settings,
    db: LibraryDatabase,
    profile: dict[str, Any],
) -> None:
    st.title("Settings & About")
    current = db.get_profile(int(profile["id"])) or profile
    brand1, brand2 = st.columns([1, 3])
    with brand1:
        st.image(str(LOGO_FULL_PATH), width=220)
    with brand2:
        st.subheader("BookVerse")
        st.write(
            "A modern discovery app for book nerds — with isolated profiles, personal libraries and recommendations that learn from each reader."
        )
        st.caption(f"Signed in as **{current['display_name']}** (@{current['username']})")

    st.subheader("Your taste profile")
    existing_niches = list(current.get("favourite_niches") or [])
    standard_selected = [value for value in existing_niches if value in COMMON_NICHES]
    custom_existing = [value for value in existing_niches if value not in COMMON_NICHES]
    with st.form("edit_profile_preferences"):
        display_name = st.text_input("Display name", value=current["display_name"])
        selected_niches = st.multiselect(
            "Favourite niches",
            COMMON_NICHES,
            default=standard_selected,
        )
        custom_niches = st.text_input(
            "Other niches",
            value=", ".join(custom_existing),
            placeholder="Comma-separated",
        )
        top_books = st.text_area(
            "Top books",
            value="\n".join(current.get("top_books") or []),
            height=150,
            help="One book per line. These choices are included in your personal taste profile.",
        )
        save_preferences = st.form_submit_button("Save taste profile", type="primary", use_container_width=True)
    if save_preferences:
        extra = [value.strip() for value in custom_niches.split(",") if value.strip()]
        books = [value.strip() for value in top_books.splitlines() if value.strip()]
        try:
            db.update_profile_preferences(display_name, [*selected_niches, *extra], books)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.session_state.pop("personalised_fingerprint", None)
            st.success("Taste profile updated.")
            st.rerun()

    with st.expander("Change profile PIN"):
        with st.form("change_pin_form"):
            current_pin = st.text_input("Current PIN", type="password")
            new_pin = st.text_input("New PIN", type="password")
            confirm_pin = st.text_input("Confirm new PIN", type="password")
            change_pin = st.form_submit_button("Change PIN", use_container_width=True)
        if change_pin:
            if new_pin != confirm_pin:
                st.error("The new PINs do not match.")
            else:
                try:
                    db.change_pin(current_pin, new_pin)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("PIN changed.")

    with st.expander("Delete this profile"):
        st.error(
            "This permanently deletes this profile, its shelves, ratings, reviews and reading history from this BookVerse installation."
        )
        with st.form("delete_profile_form"):
            delete_username = st.text_input(
                "Type the username to confirm",
                placeholder=current["username"],
            )
            delete_pin = st.text_input("Enter the profile PIN", type="password")
            confirm_delete = st.checkbox("I understand this cannot be undone")
            delete_profile = st.form_submit_button("Permanently delete profile", use_container_width=True)
        if delete_profile:
            if delete_username.strip().casefold() != str(current["username"]).casefold():
                st.error("The username confirmation does not match.")
            elif not confirm_delete:
                st.error("Tick the confirmation box before deleting the profile.")
            else:
                try:
                    db.delete_profile(int(current["id"]), delete_pin)
                except (ValueError, KeyError) as exc:
                    st.error(str(exc))
                else:
                    st.session_state.clear()
                    st.success("Profile deleted.")
                    st.rerun()

    st.subheader("What this version does")
    st.markdown(
        """
        - PIN-locked local profiles with separate libraries, shelves, goals and taste data
        - Exact-book top picks during setup, automatically marked as Finished
        - Profile deletion with username, PIN and irreversible-action confirmation
        - Search-result pagination with Previous and Next page controls
        - Personalised **For You** recommendations after at least three saved books
        - Taste learning from favourites, ratings, finished books, chosen niches and top books
        - Live searches across Open Library and Google Books
        - Natural-language search, Book DNA matching and rating filters
        - CSV export and profile-specific JSON backup/restore
        """
    )
    st.warning(
        "The profile PIN protects local access on this installation. Before a public internet deployment, replace it with proper hosted authentication and move data to PostgreSQL."
    )
    st.subheader("Data location")
    st.code(str(settings.database_path), language="text")
    if st.button("Clear cached API responses"):
        st.cache_data.clear()
        st.session_state.pop("personalised_fingerprint", None)
        st.success("API cache cleared.")


def _filter_books(
    books: list[Book],
    min_rating: float,
    max_pages: int,
    year_from: int,
    year_to: int,
    plan: SmartSearchPlan,
) -> list[Book]:
    effective_max_pages = plan.max_pages or max_pages
    effective_year_from = plan.year_from or year_from
    effective_year_to = plan.year_to or year_to
    output: list[Book] = []
    for book in books:
        if min_rating > 0 and (book.average_rating is None or book.average_rating < min_rating):
            continue
        if effective_max_pages > 0 and book.page_count and book.page_count > effective_max_pages:
            continue
        if plan.min_pages and book.page_count and book.page_count < plan.min_pages:
            continue
        if effective_year_from > 0 and book.published_year and book.published_year < effective_year_from:
            continue
        if effective_year_to > 0 and book.published_year and book.published_year > effective_year_to:
            continue
        haystack = " ".join([book.title, book.description, book.category_text]).casefold()
        if any(term.casefold() in haystack for term in plan.negative_terms):
            continue
        output.append(book)
    return output



@lru_cache(maxsize=4)
def _image_data_uri(path_text: str) -> str:
    path = Path(path_text)
    suffix = path.suffix.lower().lstrip(".") or "png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{suffix};base64,{data}"


def _loader_html(title: str, subtitle: str) -> str:
    image_uri = _image_data_uri(str(LOGO_ICON_PATH))
    return f"""
    <div class="brand-loader">
      <img src="{image_uri}" alt="BookVerse logo">
      <div>
        <div class="loader-title">{_escape(title)}</div>
        <div class="loader-sub">{_escape(subtitle)}</div>
      </div>
    </div>
    """



def _entries_dataframe(entries: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for entry in entries:
        book: Book = entry["book"]
        rows.append(
            {
                "Title": book.title,
                "Authors": book.author_text,
                "Shelf": entry["shelf"],
                "Your rating": entry["user_rating"],
                "Pages read": entry["progress_pages"],
                "Book pages": book.page_count,
                "Published": book.published_date,
                "Categories": book.category_text,
                "ISBN": book.primary_isbn,
                "Source": book.source,
                "Link": book.info_link,
                "Review": entry["review"],
            }
        )
    return pd.DataFrame(rows)


def _escape(text: str) -> str:
    import html
    return html.escape(text)
