from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

import pandas as pd
import streamlit as st

from .cache import cached_enrich_library_book, cached_mood_search
from .config import Settings, get_settings
from .database import LibraryDatabase
from .models import Book
from .persistent_cache import cache_stats, prune_cache
from .recommendation_intelligence import (
    DEFAULT_RULES,
    RULES_SETTING_KEY,
    book_dna,
    normalise_rules,
    rule_rejections,
    rules_summary,
)

FORMATS = ("Unspecified", "Paperback", "Hardback", "eBook", "Kindle", "Audiobook", "Special edition")
OWNERSHIP = ("Unspecified", "Owned", "Library loan", "Borrowed", "Wishlist")
FEEDBACK_OPTIONS = (
    "Interested", "More like this", "Not interested", "Hide this book",
    "Hide this author", "Already read another edition", "Wrong genre",
    "Too old", "Too long", "Too short", "Too much romance",
    "Not dark enough", "Too extreme", "Less romance", "More intense",
    "Lighter read",
)


def render_recommendation_feedback(db: LibraryDatabase, book: Book, key_prefix: str) -> None:
    with st.expander("Teach BookVerse", expanded=False):
        st.caption("This changes future recommendation scans. It does not add the book to your library.")
        columns = st.columns(4)
        actions = (
            ("More like this", "👍 More like this"),
            ("Not interested", "👎 Not for me"),
            ("Hide this book", "🙈 Hide book"),
            ("Hide this author", "🚫 Hide author"),
        )
        for column, (feedback, label) in zip(columns, actions):
            if column.button(label, key=f"feedback_{key_prefix}_{feedback}_{book.uid}", use_container_width=True):
                db.set_recommendation_feedback(book, feedback)
                st.session_state.personalised_dirty = True
                st.toast("Feedback saved for the next scan")
                st.rerun()

        preference_col, save_col = st.columns([3, 1], vertical_alignment="bottom")
        preference = preference_col.selectbox(
            "More specific feedback",
            (
                "Interested", "Already read another edition", "Wrong genre",
                "Too old", "Too long", "Too short", "Too much romance",
                "Not dark enough", "Too extreme", "Less romance",
                "More intense", "Lighter read",
            ),
            key=f"feedback_preference_{key_prefix}_{book.uid}",
        )
        if save_col.button("Save", key=f"feedback_save_{key_prefix}_{book.uid}", use_container_width=True):
            db.set_recommendation_feedback(book, preference)
            st.session_state.personalised_dirty = True
            st.toast("Preference saved for the next scan")
            st.rerun()



def render_recommendation_preferences(db: LibraryDatabase) -> None:
    st.subheader("Recommendation rules")
    stored = db.get_setting(RULES_SETTING_KEY, "")
    rules = normalise_rules(stored)
    st.caption(
        "These are hard filters for future Fast and Deep scans. "
        "The current saved recommendation set stays unchanged until you refresh it."
    )

    with st.form("recommendation_rules_form"):
        a1, a2, a3, a4 = st.columns(4)
        english_only = a1.toggle("English only", value=bool(rules["english_only"]))
        adult_only = a2.toggle("Adults only", value=bool(rules["adult_only"]))
        require_description = a3.toggle("Require description", value=bool(rules["require_description"]))
        standalone_only = a4.toggle("Standalone only", value=bool(rules["standalone_only"]))

        b1, b2, b3, b4 = st.columns(4)
        exclude_textbooks = b1.toggle("Exclude textbooks", value=bool(rules["exclude_textbooks"]))
        exclude_reference = b2.toggle("Exclude manuals/reference", value=bool(rules["exclude_reference"]))
        exclude_childrens = b3.toggle("Exclude children's books", value=bool(rules["exclude_childrens"]))
        exclude_nonfiction = b4.toggle("Exclude nonfiction", value=bool(rules["exclude_nonfiction"]))

        c1, c2, c3 = st.columns(3)
        exclude_poetry = c1.toggle("Exclude poetry", value=bool(rules["exclude_poetry"]))
        exclude_graphic_novels = c2.toggle("Exclude graphic novels", value=bool(rules["exclude_graphic_novels"]))
        exclude_religion = c3.toggle("Exclude religious books", value=bool(rules["exclude_religion"]))

        d1, d2, d3 = st.columns(3)
        minimum_public_rating = d1.slider(
            "Minimum public rating", 0.0, 5.0,
            float(rules["minimum_public_rating"]), 0.5,
        )
        minimum_rating_count = d2.number_input(
            "Minimum number of public ratings", min_value=0, max_value=1_000_000,
            value=int(rules["minimum_rating_count"]), step=10,
        )
        diversity = d3.slider(
            "Recommendation diversity", 0, 100, int(rules["diversity"]), 5,
            help="0 stays tightly focused. 100 deliberately spreads authors, genres and themes.",
        )

        e1, e2, e3, e4 = st.columns(4)
        minimum_pages = e1.number_input(
            "Minimum pages", min_value=0, max_value=5000,
            value=int(rules["minimum_pages"]), step=25,
        )
        maximum_pages = e2.number_input(
            "Maximum pages", min_value=0, max_value=5000,
            value=int(rules["maximum_pages"]), step=25,
        )
        published_from = e3.number_input(
            "Published from", min_value=0, max_value=2100,
            value=int(rules["published_from"]), step=1,
        )
        published_to = e4.number_input(
            "Published by", min_value=0, max_value=2100,
            value=int(rules["published_to"]), step=1,
        )

        f1, f2 = st.columns(2)
        maximum_per_author = f1.slider(
            "Maximum recommendations per author", 1, 6,
            int(rules["maximum_per_author"]),
        )
        maximum_per_primary_genre = f2.slider(
            "Maximum recommendations per main genre", 1, 12,
            int(rules["maximum_per_primary_genre"]),
        )
        save_rules = st.form_submit_button(
            "Save recommendation rules", type="primary", use_container_width=True
        )

    if save_rules:
        updated = normalise_rules(
            {
                "english_only": english_only,
                "adult_only": adult_only,
                "require_description": require_description,
                "standalone_only": standalone_only,
                "exclude_textbooks": exclude_textbooks,
                "exclude_reference": exclude_reference,
                "exclude_childrens": exclude_childrens,
                "exclude_nonfiction": exclude_nonfiction,
                "exclude_poetry": exclude_poetry,
                "exclude_graphic_novels": exclude_graphic_novels,
                "exclude_religion": exclude_religion,
                "minimum_public_rating": minimum_public_rating,
                "minimum_rating_count": int(minimum_rating_count),
                "minimum_pages": int(minimum_pages),
                "maximum_pages": int(maximum_pages),
                "published_from": int(published_from),
                "published_to": int(published_to),
                "diversity": int(diversity),
                "maximum_per_author": int(maximum_per_author),
                "maximum_per_primary_genre": int(maximum_per_primary_genre),
            }
        )
        db.set_setting(RULES_SETTING_KEY, json.dumps(updated, ensure_ascii=False))
        st.session_state.personalised_dirty = True
        st.success("Recommendation rules saved. Refresh recommendations when you are ready to apply them.")

    st.caption("Active rules: " + " · ".join(rules_summary(db.get_setting(RULES_SETTING_KEY, ""))))


def render_feedback_memory(db: LibraryDatabase) -> None:
    with st.expander("Recommendation memory", expanded=False):
        feedback = db.list_recommendation_feedback()
        if not feedback:
            st.info("No recommendation feedback has been saved yet.")
            return
        st.caption(
            "BookVerse uses this memory only when you deliberately run the next recommendation scan."
        )
        rows = [
            {
                "Book": item.get("title") or item.get("uid"),
                "Author": item.get("author") or "",
                "Feedback": item.get("feedback") or "",
                "Updated": item.get("updated_at") or "",
            }
            for item in feedback
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        labels = {
            f"{item.get('title') or item.get('uid')} — {item.get('feedback')}": item
            for item in feedback
        }
        r1, r2 = st.columns([3, 1])
        selected = r1.selectbox("Remove one memory", tuple(labels), key="feedback_memory_remove")
        if r2.button("Remove", use_container_width=True, key="feedback_memory_remove_button"):
            db.delete_recommendation_feedback(str(labels[selected]["uid"]))
            st.session_state.personalised_dirty = True
            st.rerun()
        if st.button("Clear all recommendation memory", use_container_width=True):
            removed = db.clear_recommendation_feedback()
            st.session_state.personalised_dirty = True
            st.success(f"Removed {removed} saved feedback records.")
            st.rerun()


def render_choose_next_book(db: LibraryDatabase) -> None:
    with st.expander("Choose My Next Book", expanded=False):
        raw = db.get_setting("personalised_last_results_v21", "") or db.get_setting("personalised_last_results_v20", "")
        if not raw:
            st.info("Build a recommendation set first, then this tool can narrow it to three finalists without another scan.")
            return
        try:
            saved = json.loads(raw)
            payloads = list(saved.get("results") or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            payloads = []
        if not payloads:
            st.info("No saved recommendation set is available yet.")
            return

        with st.form("choose_next_book_form"):
            q1, q2, q3, q4 = st.columns(4)
            length = q1.selectbox("Reading commitment", ("Any", "Short under 250 pages", "Medium 250 to 450", "Long over 450"))
            mood = q2.selectbox("Mood", ("Any", "Light", "Dark", "Suspenseful", "Emotional"))
            series = q3.selectbox("Series preference", ("Any", "Standalone", "Series"))
            approach = q4.selectbox("Approach", ("Closest match", "Balanced", "Something different"))
            choose = st.form_submit_button("Choose three finalists", type="primary", use_container_width=True)

        if choose:
            ranked: list[tuple[float, dict[str, Any], Book]] = []
            for payload in payloads:
                try:
                    book = Book.from_dict(payload.get("book") or payload)
                except (TypeError, ValueError, KeyError):
                    continue
                dna = payload.get("dna") or book_dna(book)
                score = float(payload.get("match_percent") or 0)
                pages = int(book.page_count or 0)
                if length == "Short under 250 pages" and pages and pages >= 250:
                    continue
                if length == "Medium 250 to 450" and pages and not 250 <= pages <= 450:
                    continue
                if length == "Long over 450" and pages and pages <= 450:
                    continue
                if mood == "Light" and dna.get("intensity") != "Light":
                    score -= 18
                elif mood == "Dark" and dna.get("intensity") not in {"Dark", "Extreme"}:
                    score -= 18
                elif mood == "Suspenseful" and dna.get("pace") != "Fast":
                    score -= 12
                elif mood == "Emotional" and "Emotional" not in dna.get("tones", []):
                    score -= 10
                series_value = str(dna.get("series") or "")
                if series == "Standalone" and "Series" in series_value:
                    continue
                if series == "Series" and "Series" not in series_value:
                    continue
                if approach == "Something different":
                    score = 100 - abs(score - 68)
                elif approach == "Balanced":
                    score -= abs(score - 80) * 0.2
                ranked.append((score, payload, book))
            ranked.sort(key=lambda row: row[0], reverse=True)
            st.session_state.choose_next_results = [row[1] for row in ranked[:3]]

        finalists = list(st.session_state.get("choose_next_results") or [])
        if finalists:
            columns = st.columns(len(finalists))
            for column, payload in zip(columns, finalists):
                book = Book.from_dict(payload.get("book") or payload)
                with column:
                    if book.best_cover:
                        st.image(book.best_cover, width=125)
                    st.markdown(f"**{book.display_title}**")
                    st.caption(book.author_text)
                    st.metric("Taste match", f"{int(payload.get('match_percent') or 0)}%")
                    reasons = list(payload.get("reasons") or [])
                    if reasons:
                        st.caption(" · ".join(reasons[:2]))
                    b1, b2 = st.columns(2)
                    if b1.button("Want to Read", key=f"choose_want_{book.uid}", use_container_width=True):
                        db.save_entry(book, "Want to Read")
                        st.session_state.personalised_dirty = True
                        st.rerun()
                    if b2.button("Read", key=f"choose_read_{book.uid}", use_container_width=True):
                        db.save_entry(book, "Finished", progress_pages=int(book.page_count or 0))
                        st.session_state.personalised_dirty = True
                        st.rerun()

def render_mood_finder(
    settings: Settings,
    db: LibraryDatabase,
    api_key: str,
    render_grid: Callable[[list[Book], LibraryDatabase, Settings, str, str], None],
) -> None:
    with st.expander("Mood Finder", expanded=False):
        st.write("Describe exactly what you want to read, then BookVerse searches both catalogues and ranks the closest matches.")
        with st.form("mood_finder_form"):
            mood = st.text_input("Mood or premise", placeholder="Dark psychological horror in an isolated setting")
            c1, c2, c3, c4 = st.columns(4)
            genre = c1.selectbox("Genre", ("Any", "Horror", "Thriller", "Fantasy", "Romance", "Science fiction", "Mystery", "Historical", "Nonfiction"))
            intensity = c2.selectbox("Intensity", ("Any", "Light", "Moderate", "Dark", "Extreme"))
            romance = c3.selectbox("Romance level", ("Any", "None", "Low", "Medium", "High"))
            pace = c4.selectbox("Pace", ("Any", "Fast", "Balanced", "Slow burn"))
            f1, f2, f3 = st.columns(3)
            min_rating = f1.slider("Minimum public rating", 0.0, 5.0, 0.0, 0.5)
            max_pages = f2.number_input("Maximum pages, 0 for any", min_value=0, max_value=3000, value=0, step=50)
            series_preference = f3.selectbox("Standalone or series", ("Any", "Standalone", "Series"))
            y1, y2 = st.columns(2)
            year_from = y1.number_input("Published from, 0 for any", min_value=0, max_value=2100, value=0, step=1)
            year_to = y2.number_input("Published by, 0 for any", min_value=0, max_value=2100, value=0, step=1)
            search = st.form_submit_button("Find books for this mood", type="primary", use_container_width=True)

        if search:
            parts = [mood.strip()]
            if genre != "Any":
                parts.append(genre)
            if intensity != "Any":
                parts.append(f"{intensity.lower()} intensity")
            if romance != "Any":
                parts.append(f"{romance.lower()} romance")
            if pace != "Any":
                parts.append(f"{pace.lower()} pace")
            query = ", ".join(part for part in parts if part)
            if not query:
                st.warning("Describe the mood or choose at least one filter.")
            else:
                token = int(st.session_state.get("mood_refresh_token", 0)) + 1
                st.session_state.mood_refresh_token = token
                with st.spinner("Matching your reading mood…"):
                    payloads, messages = cached_mood_search(
                        query,
                        api_key,
                        settings.open_library_contact,
                        settings.request_timeout_seconds,
                        float(min_rating),
                        int(max_pages),
                        series_preference == "Standalone",
                        str(db.path),
                        token,
                        int(year_from),
                        int(year_to),
                        series_preference,
                    )
                st.session_state.mood_results = payloads
                st.session_state.mood_messages = messages
                st.session_state.mood_query = query
                db.set_setting(
                    "last_mood_results",
                    json.dumps({"query": query, "results": payloads, "messages": messages}, ensure_ascii=False),
                )

        if "mood_results" not in st.session_state:
            saved = db.get_setting("last_mood_results", "")
            if saved:
                try:
                    payload = json.loads(saved)
                    st.session_state.mood_results = payload.get("results") or []
                    st.session_state.mood_messages = payload.get("messages") or []
                    st.session_state.mood_query = payload.get("query") or ""
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

        for message in st.session_state.get("mood_messages", []):
            st.caption(message)
        results = [Book.from_dict(item) for item in st.session_state.get("mood_results", [])]
        if results:
            st.markdown(f"#### Mood matches: {st.session_state.get('mood_query', '')}")
            render_grid(results, db, settings, api_key, "mood")


def render_entry_tracking(db: LibraryDatabase, entry: dict[str, Any]) -> None:
    book: Book = entry["book"]
    st.divider()
    st.subheader("Edition, ownership and series")
    with st.form(f"tracking_metadata_{entry['uid']}"):
        c1, c2 = st.columns(2)
        format_index = FORMATS.index(entry.get("format", "Unspecified")) if entry.get("format") in FORMATS else 0
        ownership_index = OWNERSHIP.index(entry.get("ownership", "Unspecified")) if entry.get("ownership") in OWNERSHIP else 0
        format_name = c1.selectbox("Format", FORMATS, index=format_index)
        ownership = c2.selectbox("Ownership", OWNERSHIP, index=ownership_index)
        s1, s2, s3 = st.columns(3)
        series_name = s1.text_input("Series name", value=entry.get("series_name") or "")
        series_number = s2.number_input(
            "Series number",
            min_value=0.0,
            max_value=999.0,
            value=float(entry.get("series_number") or 0.0),
            step=0.5,
        )
        reread_count = s3.number_input("Reread count", min_value=0, max_value=999, value=int(entry.get("reread_count") or 0))
        audio_minutes = st.number_input(
            "Audiobook progress in minutes",
            min_value=0,
            max_value=100000,
            value=int(entry.get("audio_progress_minutes") or 0),
        )
        tags = st.text_input("Personal tags", value=", ".join(entry.get("personal_tags") or []), placeholder="cosy, autumn, book club")
        warnings = st.text_input("Content warnings", value=", ".join(entry.get("content_warnings") or []), placeholder="violence, grief")
        save_metadata = st.form_submit_button("Save tracking details", type="primary", use_container_width=True)
    if save_metadata:
        db.update_entry_metadata(
            entry["uid"],
            format_name=format_name,
            ownership=ownership,
            audio_progress_minutes=int(audio_minutes),
            reread_count=int(reread_count),
            series_name=series_name,
            series_number=float(series_number) if series_number > 0 else None,
            personal_tags=[value.strip() for value in tags.split(",") if value.strip()],
            content_warnings=[value.strip() for value in warnings.split(",") if value.strip()],
        )
        st.toast("Book tracking details saved")
        st.rerun()

    st.subheader("Reading session")
    with st.form(f"reading_session_{entry['uid']}"):
        r1, r2, r3 = st.columns(3)
        session_date = r1.date_input("Date", value=date.today())
        pages = r2.number_input("Pages read", min_value=0, max_value=10000, value=0)
        minutes = r3.number_input("Minutes read", min_value=0, max_value=10000, value=0)
        session_notes = st.text_input("Session note", placeholder="Where you stopped or how it felt")
        add_session = st.form_submit_button("Add reading session", use_container_width=True)
    if add_session:
        db.add_reading_session(entry["uid"], session_date.isoformat(), int(pages), int(minutes), session_notes)
        if pages:
            new_progress = int(entry.get("progress_pages") or 0) + int(pages)
            db.update_entry(entry["uid"], entry["shelf"], entry.get("user_rating"), entry.get("review") or "", new_progress)
        st.toast("Reading session added")
        st.rerun()

    sessions = db.list_reading_sessions(entry["uid"])
    if sessions:
        session_df = pd.DataFrame(sessions[:12])[["session_date", "pages_read", "minutes_read", "notes"]]
        session_df.columns = ["Date", "Pages", "Minutes", "Notes"]
        st.dataframe(session_df, use_container_width=True, hide_index=True)

    st.subheader("Reading journal")
    with st.form(f"journal_note_{entry['uid']}"):
        j1, j2 = st.columns([1, 3])
        note_type = j1.selectbox("Type", ("Note", "Quote", "Thought", "Character", "Prediction", "Review draft"))
        page_number = j1.number_input("Page", min_value=0, max_value=max(book.page_count or 10000, 10000), value=0)
        note_text = j2.text_area("Journal entry", height=120)
        add_note = st.form_submit_button("Add journal entry", use_container_width=True)
    if add_note:
        try:
            db.add_journal_note(entry["uid"], note_text, note_type, int(page_number) if page_number else None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.toast("Journal entry saved")
            st.rerun()

    notes = db.list_journal_notes(entry["uid"])
    for note in notes[:10]:
        with st.container(border=True):
            label = note["note_type"]
            if note.get("page_number") is not None:
                label += f" · page {note['page_number']}"
            st.markdown(f"**{label}**")
            st.write(note["note_text"])
            st.caption(note["created_at"])
            if st.button("Delete note", key=f"delete_note_{note['id']}"):
                db.delete_journal_note(int(note["id"]))
                st.rerun()


def render_library_tools(db: LibraryDatabase) -> None:
    with st.expander("Library tools", expanded=False):
        series_tab, shortlist_tab, duplicate_tab, health_tab = st.tabs(("Series tracker", "Shortlists", "Duplicates", "Library health"))
        with series_tab:
            series = db.series_summary()
            if not series:
                st.info("Add a series name and number from any book’s details to build this tracker.")
            for item in series:
                progress = item["finished"] / max(item["total"], 1)
                st.markdown(f"#### {item['name']}")
                st.progress(progress, text=f"{item['finished']} of {item['total']} books read")
                if item.get("next"):
                    next_entry = item["next"]
                    st.caption(f"Next in your library: {next_entry['book'].display_title}")
                known_numbers = {
                    int(entry["series_number"])
                    for entry in item["books"]
                    if entry.get("series_number") is not None and float(entry["series_number"]).is_integer()
                }
                if known_numbers:
                    missing = [number for number in range(1, max(known_numbers) + 1) if number not in known_numbers]
                    if missing:
                        st.warning("Missing from this series: " + ", ".join(f"book {number}" for number in missing))
                rows = [
                    {
                        "#": entry.get("series_number") or "",
                        "Title": entry["book"].display_title,
                        "Author": entry["book"].author_text,
                        "Shelf": "Read" if entry["shelf"] == "Finished" else entry["shelf"],
                    }
                    for entry in item["books"]
                ]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        with shortlist_tab:
            with st.form("create_shortlist_form"):
                new_name = st.text_input("New shortlist name", placeholder="What should I read next?")
                create = st.form_submit_button("Create shortlist")
            if create:
                try:
                    db.create_shortlist(new_name)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.rerun()
            shortlists = db.list_shortlists()
            if not shortlists:
                st.info("Create a shortlist, then add books from their full details.")
            else:
                labels = {f"{item['name']} · {item['book_count']} books": item for item in shortlists}
                selected_label = st.selectbox("Open shortlist", tuple(labels), key="shortlist_open")
                selected = labels[selected_label]
                books = db.shortlist_books(int(selected["id"]))
                if books:
                    compare_rows = []
                    for item in books:
                        book = item["book"]
                        compare_rows.append(
                            {
                                "Title": book.display_title,
                                "Author": book.author_text,
                                "Pages": book.page_count,
                                "Rating": book.average_rating,
                                "Year": book.published_year,
                                "Genres": ", ".join(book.categories[:4]),
                            }
                        )
                    st.dataframe(pd.DataFrame(compare_rows), use_container_width=True, hide_index=True)
                    remove_map = {f"{item['book'].display_title} — {item['book'].author_text}": item for item in books}
                    remove_label = st.selectbox("Remove a book", ("", *remove_map), key="shortlist_remove_book")
                    if remove_label and st.button("Remove selected book from shortlist"):
                        db.remove_from_shortlist(int(selected["id"]), remove_map[remove_label]["uid"])
                        st.rerun()
                else:
                    st.info("This shortlist is empty.")
                if st.button("Delete this shortlist", key=f"delete_shortlist_{selected['id']}"):
                    db.delete_shortlist(int(selected["id"]))
                    st.rerun()

        with duplicate_tab:
            groups = db.duplicate_groups()
            if not groups:
                st.success("No likely duplicate editions are saved.")
            for group_index, group in enumerate(groups):
                st.markdown(f"**Possible duplicate: {group[0]['book'].display_title}**")
                labels = {
                    (
                        f"{entry['book'].display_title} · {entry['book'].source} · "
                        f"{entry['book'].published_date or 'unknown year'} · "
                        f"{entry['book'].primary_isbn or 'no ISBN'}"
                    ): entry
                    for entry in group
                }
                preferred_label = st.selectbox(
                    "Edition to keep",
                    tuple(labels),
                    key=f"duplicate_preferred_{group_index}",
                )
                st.caption(
                    "Merging keeps the selected edition and combines the strongest shelf status, "
                    "progress, rating, reviews, tracking details, sessions, journal notes and shortlist links."
                )
                if st.button("Merge duplicate editions", key=f"duplicate_merge_{group_index}", use_container_width=True):
                    preferred = labels[preferred_label]
                    duplicate_uids = [entry["uid"] for entry in group if entry["uid"] != preferred["uid"]]
                    merged = db.merge_duplicate_entries(preferred["uid"], duplicate_uids)
                    st.success(f"Merged {merged} duplicate {'edition' if merged == 1 else 'editions'}.")
                    st.rerun()


        with health_tab:
            entries = db.list_entries("All")
            missing_descriptions = [entry for entry in entries if len(entry["book"].description.strip()) < 60]
            missing_covers = [entry for entry in entries if not entry["book"].best_cover]
            missing_pages = [entry for entry in entries if not entry["book"].page_count]
            weak_categories = [entry for entry in entries if len(entry["book"].categories) < 2]
            duplicate_count = sum(max(0, len(group) - 1) for group in db.duplicate_groups())
            h1, h2, h3, h4, h5 = st.columns(5)
            h1.metric("Saved books", len(entries))
            h2.metric("Missing descriptions", len(missing_descriptions))
            h3.metric("Missing covers", len(missing_covers))
            h4.metric("Missing page counts", len(missing_pages))
            h5.metric("Duplicate editions", duplicate_count)

            unhealthy_map: dict[str, dict[str, Any]] = {}
            for entry in entries:
                problems: list[str] = []
                book = entry["book"]
                if len(book.description.strip()) < 60:
                    problems.append("description")
                if not book.best_cover:
                    problems.append("cover")
                if not book.page_count:
                    problems.append("page count")
                if len(book.categories) < 2:
                    problems.append("categories")
                if problems:
                    unhealthy_map[
                        f"{book.display_title} — {book.author_text} · missing {', '.join(problems)}"
                    ] = entry

            if not unhealthy_map:
                st.success("Every saved book has a healthy core catalogue record.")
            else:
                st.caption(
                    "Repairing searches for richer metadata but preserves the shelf, rating, review, progress and tracking data."
                )
                selected_label = st.selectbox(
                    "Book to repair", tuple(unhealthy_map), key="library_health_selected"
                )
                if st.button("Repair selected book metadata", type="primary", use_container_width=True):
                    selected = unhealthy_map[selected_label]
                    book = selected["book"]
                    settings = get_settings()
                    with st.spinner("Finding the richest matching catalogue record…"):
                        payload = cached_enrich_library_book(
                            book.to_dict(),
                            settings.google_books_api_key,
                            settings.open_library_contact,
                            settings.request_timeout_seconds,
                            engine_version="v21-library-health",
                            database_path=str(settings.database_path),
                        )
                    repaired_payload = dict(payload)
                    repaired_payload["source"] = book.source
                    repaired_payload["source_id"] = book.source_id
                    repaired = Book.from_dict(repaired_payload)
                    db.save_entry(
                        repaired,
                        selected["shelf"],
                        user_rating=selected.get("user_rating"),
                        review=str(selected.get("review") or ""),
                        progress_pages=int(selected.get("progress_pages") or 0),
                    )
                    st.success(f"Repaired catalogue metadata for {repaired.display_title}.")
                    st.rerun()


def render_shortlist_add_control(db: LibraryDatabase, uid: str, key_suffix: str) -> None:
    if db.get_entry(uid) is None:
        st.caption("Save this book to your library before adding it to a shortlist.")
        return
    shortlists = db.list_shortlists()
    if not shortlists:
        return
    labels = {item["name"]: item for item in shortlists}
    c1, c2 = st.columns([3, 1])
    selected = c1.selectbox("Add to shortlist", tuple(labels), key=f"shortlist_select_{key_suffix}")
    if c2.button("Add", key=f"shortlist_add_{key_suffix}", use_container_width=True):
        db.add_to_shortlist(int(labels[selected]["id"]), uid)
        st.toast(f"Added to {selected}")


def render_advanced_stats(db: LibraryDatabase) -> None:
    entries = db.list_entries("All")
    sessions = db.list_reading_sessions()
    if not entries:
        return
    st.subheader("Reading insights")
    formats = pd.Series([entry.get("format") or "Unspecified" for entry in entries]).value_counts()
    ownership = pd.Series([entry.get("ownership") or "Unspecified" for entry in entries]).value_counts()
    c1, c2, c3, c4 = st.columns(4)
    total_minutes = sum(int(session.get("minutes_read") or 0) for session in sessions)
    logged_pages = sum(int(session.get("pages_read") or 0) for session in sessions)
    rereads = sum(int(entry.get("reread_count") or 0) for entry in entries)
    dnf_count = sum(entry["shelf"] == "DNF" for entry in entries)
    c1.metric("Reading time logged", f"{total_minutes // 60}h {total_minutes % 60}m")
    c2.metric("Session pages logged", f"{logged_pages:,}")
    c3.metric("Rereads", rereads)
    c4.metric("DNF rate", f"{dnf_count / max(len(entries), 1) * 100:.1f}%")

    session_days = sorted({str(session.get("session_date") or "")[:10] for session in sessions if session.get("session_date")})
    streak = 0
    if session_days:
        from datetime import date as _date, timedelta
        day_set = {_date.fromisoformat(value) for value in session_days}
        cursor = max(day_set)
        while cursor in day_set:
            streak += 1
            cursor -= timedelta(days=1)
    finished = [entry for entry in entries if entry["shelf"] == "Finished"]
    completion_days = []
    for entry in finished:
        if entry.get("started_at") and entry.get("finished_at"):
            try:
                start_date = pd.to_datetime(entry["started_at"])
                finish_date = pd.to_datetime(entry["finished_at"])
                completion_days.append(max(0, (finish_date - start_date).days))
            except Exception:
                pass
    extra1, extra2, extra3 = st.columns(3)
    extra1.metric("Current reading streak", f"{streak} days")
    extra2.metric("Average completion time", f"{sum(completion_days) / len(completion_days):.1f} days" if completion_days else "—")
    current_year = date.today().year
    finished_this_year = sum(str(entry.get("finished_at") or "").startswith(str(current_year)) for entry in finished)
    days_elapsed = max(1, date.today().timetuple().tm_yday)
    predicted = round(finished_this_year / days_elapsed * 365) if finished_this_year else 0
    extra3.metric("Predicted yearly total", predicted)

    current_month = date.today().strftime("%Y-%m")
    finished_this_month = sum(str(entry.get("finished_at") or "").startswith(current_month) for entry in finished)
    recent_cutoff = pd.Timestamp(date.today()) - pd.Timedelta(days=30)
    recent_pages = 0
    for session in sessions:
        try:
            session_day = pd.Timestamp(str(session.get("session_date") or ""))
        except Exception:
            continue
        if session_day >= recent_cutoff:
            recent_pages += int(session.get("pages_read") or 0)
    wrap1, wrap2, wrap3 = st.columns(3)
    wrap1.metric("Finished this month", finished_this_month)
    wrap2.metric("Finished this year", finished_this_year)
    wrap3.metric("30-day reading pace", f"{recent_pages / 30:.1f} pages/day" if recent_pages else "—")

    page_entries = [entry for entry in entries if entry["book"].page_count]
    if page_entries:
        longest = max(page_entries, key=lambda entry: int(entry["book"].page_count or 0))
        shortest = min(page_entries, key=lambda entry: int(entry["book"].page_count or 0))
        length1, length2 = st.columns(2)
        length1.metric("Longest saved book", f"{int(longest['book'].page_count or 0):,} pages", longest["book"].display_title)
        length2.metric("Shortest saved book", f"{int(shortest['book'].page_count or 0):,} pages", shortest["book"].display_title)

    author_counts: dict[str, int] = {}
    for entry in entries:
        for author in entry["book"].authors or ("Unknown author",):
            author_counts[author] = author_counts.get(author, 0) + 1
    if author_counts:
        favourite_authors = pd.Series(dict(sorted(author_counts.items(), key=lambda item: item[1], reverse=True)[:10]), name="Books")
        st.markdown("**Most-read authors in your library**")
        st.bar_chart(favourite_authors)

    genre_ratings: dict[str, list[float]] = {}
    for entry in entries:
        if entry.get("user_rating") is None:
            continue
        categories = entry["book"].categories or ("Uncategorised",)
        for category in categories[:3]:
            genre_ratings.setdefault(category, []).append(float(entry["user_rating"]))
    if genre_ratings:
        averages = {
            genre: sum(values) / len(values)
            for genre, values in genre_ratings.items()
            if values
        }
        top_genre_ratings = pd.Series(
            dict(sorted(averages.items(), key=lambda item: item[1], reverse=True)[:10]),
            name="Average rating",
        )
        st.markdown("**Your highest-rated genres**")
        st.bar_chart(top_genre_ratings)

    chart1, chart2 = st.columns(2)
    with chart1:
        st.markdown("**Formats**")
        st.bar_chart(formats)
    with chart2:
        st.markdown("**Ownership**")
        st.bar_chart(ownership)
    if sessions:
        session_df = pd.DataFrame(sessions)
        session_df["session_date"] = pd.to_datetime(session_df["session_date"], errors="coerce")
        session_df = session_df.dropna(subset=["session_date"])
        if not session_df.empty:
            by_month = session_df.groupby(session_df["session_date"].dt.to_period("M").astype(str))[["pages_read", "minutes_read"]].sum()
            st.markdown("**Reading activity by month**")
            st.line_chart(by_month)


def render_diagnostics(settings: Settings, db: LibraryDatabase) -> None:
    st.subheader("Cloud and scan diagnostics")
    stats = cache_stats(settings.database_path)
    c1, c2, c3 = st.columns(3)
    c1.metric("Persistent cache entries", stats["entries"])
    c2.metric("Cache hits", stats["hits"])
    c3.metric("Expired entries", stats["expired"])
    if getattr(db, "cloud_enabled", False):
        st.success("Supabase cloud database is connected.")
        cloud_upload = str(getattr(db, "cloud_last_upload", "") or "")
        cloud_restore = str(getattr(db, "cloud_last_restore", "") or "")
        cloud1, cloud2 = st.columns(2)
        cloud1.metric("Last cloud save", cloud_upload or "No write in this process yet")
        cloud2.metric("Last cloud restore", cloud_restore or "No restore in this process")
    else:
        st.warning("Supabase cloud database is not enabled in this session.")
    history = db.list_scan_history(12)
    if history:
        rows = [
            {
                "When": item["created_at"],
                "Type": item["scan_type"],
                "Mode": item["scan_mode"],
                "Seconds": round(float(item["duration_seconds"]), 2),
                "Results": item["result_count"],
                "Estimated requests": item["requests_count"],
                "Cache hits": item["cache_hits"],
            }
            for item in history
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    b1, b2 = st.columns(2)
    if b1.button("Remove expired catalogue cache", use_container_width=True):
        removed = prune_cache(settings.database_path, clear_all=False)
        db.set_setting("cache_last_pruned", date.today().isoformat())
        st.success(f"Removed {removed} expired cache entries.")
    if b2.button("Clear all catalogue cache", use_container_width=True):
        removed = prune_cache(settings.database_path, clear_all=True)
        db.set_setting("cache_last_pruned", date.today().isoformat())
        st.success(f"Removed {removed} cached catalogue entries.")
