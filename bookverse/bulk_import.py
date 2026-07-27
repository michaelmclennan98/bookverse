from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import streamlit as st

from .cache import cached_search
from .config import get_settings
from .database import LibraryDatabase
from .models import Book


MAX_BULK_BOOKS = 25

DISPLAY_SHELVES = (
    "Want to Read",
    "Reading",
    "Read",
    "DNF",
    "Favourites",
)

PER_BOOK_SHELVES = (
    "Use default",
    *DISPLAY_SHELVES,
)


def _database_shelf(display_shelf: str) -> str:
    if display_shelf == "Read":
        return "Finished"

    return display_shelf


def _normalise_match_text(value: str) -> str:
    cleaned = " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in str(value).casefold()
        ).split()
    )

    return cleaned


def _parse_bulk_lines(
    raw_value: str,
) -> tuple[list[tuple[str, str]], list[str]]:
    parsed: list[tuple[str, str]] = []
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()

    for line_number, original_line in enumerate(
        str(raw_value).splitlines(),
        start=1,
    ):
        line = original_line.strip()

        if not line:
            continue

        line = re.sub(
            r"^\s*(?:[-*•]\s+|\d+[.)]\s*)",
            "",
            line,
        ).strip()

        delimiter = next(
            (
                candidate
                for candidate in (
                    " — ",
                    " – ",
                    " - ",
                    " | ",
                    "\t",
                )
                if candidate in line
            ),
            None,
        )

        if delimiter is None:
            errors.append(
                f"Line {line_number}: use Book title - Author."
            )
            continue

        title, author = line.rsplit(delimiter, 1)
        title = " ".join(title.split()).strip()
        author = " ".join(author.split()).strip()

        if not title or not author:
            errors.append(
                f"Line {line_number}: both the title and author are required."
            )
            continue

        duplicate_key = (
            title.casefold(),
            author.casefold(),
        )

        if duplicate_key in seen:
            continue

        seen.add(duplicate_key)
        parsed.append((title, author))

    if len(parsed) > MAX_BULK_BOOKS:
        errors.append(
            f"Only the first {MAX_BULK_BOOKS} books were processed."
        )
        parsed = parsed[:MAX_BULK_BOOKS]

    return parsed, errors


def _candidate_score(
    wanted_title: str,
    wanted_author: str,
    book: Book,
) -> float:
    wanted_title_normalised = _normalise_match_text(
        wanted_title
    )
    wanted_author_normalised = _normalise_match_text(
        wanted_author
    )

    candidate_title = _normalise_match_text(
        book.display_title
    )
    candidate_author = _normalise_match_text(
        book.author_text
    )

    title_similarity = SequenceMatcher(
        None,
        wanted_title_normalised,
        candidate_title,
    ).ratio()

    author_similarity = SequenceMatcher(
        None,
        wanted_author_normalised,
        candidate_author,
    ).ratio()

    score = (
        title_similarity * 0.72
        + author_similarity * 0.28
    )

    if (
        wanted_title_normalised
        and wanted_title_normalised == candidate_title
    ):
        score += 0.30

    if (
        wanted_author_normalised
        and wanted_author_normalised == candidate_author
    ):
        score += 0.20

    wanted_author_tokens = set(
        wanted_author_normalised.split()
    )

    candidate_author_tokens = set(
        candidate_author.split()
    )

    if (
        wanted_author_tokens
        and wanted_author_tokens.issubset(
            candidate_author_tokens
        )
    ):
        score += 0.12

    return score


def _search_bulk_candidates(
    title: str,
    author: str,
) -> tuple[list[Book], list[str]]:
    settings = get_settings()

    title_payloads, title_messages = cached_search(
        title,
        "Title",
        "Both",
        18,
        "",
        "relevance",
        "",
        settings.google_books_api_key,
        settings.open_library_contact,
        settings.request_timeout_seconds,
        0,
    )

    keyword_payloads: list[dict] = []
    keyword_messages: list[str] = []

    if len(title_payloads) < 8:
        keyword_payloads, keyword_messages = cached_search(
            f"{title} {author}",
            "Keyword",
            "Both",
            18,
            "",
            "relevance",
            "",
            settings.google_books_api_key,
            settings.open_library_contact,
            settings.request_timeout_seconds,
            0,
        )

    candidates: list[Book] = []
    seen_uids: set[str] = set()

    for payload in [
        *title_payloads,
        *keyword_payloads,
    ]:
        try:
            book = Book.from_dict(payload)
        except (
            TypeError,
            ValueError,
            KeyError,
        ):
            continue

        if book.uid in seen_uids:
            continue

        seen_uids.add(book.uid)
        candidates.append(book)

    candidates.sort(
        key=lambda book: _candidate_score(
            title,
            author,
            book,
        ),
        reverse=True,
    )

    messages = list(
        dict.fromkeys(
            [
                *title_messages,
                *keyword_messages,
            ]
        )
    )

    return candidates[:6], messages


def _candidate_label(
    book: Book,
    edition_number: int,
) -> str:
    details: list[str] = [
        book.author_text,
    ]

    if book.published_year:
        details.append(str(book.published_year))

    if book.source:
        details.append(
            "Google Books"
            if book.source == "google"
            else "Open Library"
        )

    return (
        f"{book.display_title} — "
        f"{' · '.join(details)} · "
        f"match {edition_number}"
    )


def _commit_bulk_import(
    db: LibraryDatabase,
    token: int,
) -> None:
    rows = list(
        st.session_state.get(
            "bulk_match_rows",
            [],
        )
    )

    default_display_shelf = str(
        st.session_state.get(
            f"bulk_default_shelf_{token}",
            "Want to Read",
        )
    )

    selected_entries: list[tuple[Book, str]] = []
    seen_uids: set[str] = set()

    for index, row in enumerate(rows):
        candidates = list(
            row.get("candidates") or []
        )

        selected_index = int(
            st.session_state.get(
                f"bulk_match_choice_{token}_{index}",
                0,
            )
        )

        if (
            selected_index <= 0
            or selected_index > len(candidates)
        ):
            continue

        try:
            book = Book.from_dict(
                candidates[selected_index - 1]
            )
        except (
            TypeError,
            ValueError,
            KeyError,
        ):
            continue

        if book.uid in seen_uids:
            continue

        chosen_display_shelf = str(
            st.session_state.get(
                f"bulk_match_shelf_{token}_{index}",
                "Use default",
            )
        )

        if chosen_display_shelf == "Use default":
            chosen_display_shelf = (
                default_display_shelf
            )

        seen_uids.add(book.uid)

        selected_entries.append(
            (
                book,
                _database_shelf(
                    chosen_display_shelf
                ),
            )
        )

    if not selected_entries:
        st.session_state.bulk_import_error = (
            "Choose at least one matching book before adding."
        )
        st.session_state.pop(
            "bulk_import_notice",
            None,
        )
        return

    try:
        bulk_save = getattr(
            db,
            "save_entries_bulk",
            None,
        )

        if callable(bulk_save):
            saved_count = int(
                bulk_save(selected_entries)
            )
        else:
            saved_count = 0

            for book, shelf in selected_entries:
                db.save_entry(
                    book,
                    shelf,
                    progress_pages=(
                        int(book.page_count or 0)
                        if shelf == "Finished"
                        else 0
                    ),
                )
                saved_count += 1

    except Exception as exc:
        st.session_state.bulk_import_error = (
            f"Could not save the matched books: {exc}"
        )
        st.session_state.pop(
            "bulk_import_notice",
            None,
        )
        return

    st.session_state.personalised_dirty = True
    st.session_state.bulk_match_rows = []
    st.session_state.bulk_match_messages = []
    st.session_state.bulk_match_parse_errors = []

    st.session_state.bulk_import_notice = (
        f"Added or updated {saved_count} "
        f"{'book' if saved_count == 1 else 'books'}. "
        "Your current recommendations were not refreshed."
    )

    st.session_state.pop(
        "bulk_import_error",
        None,
    )


def render_bulk_importer(
    db: LibraryDatabase,
) -> None:
    notice = st.session_state.pop(
        "bulk_import_notice",
        None,
    )

    if notice:
        st.success(str(notice))

    import_error = st.session_state.pop(
        "bulk_import_error",
        None,
    )

    if import_error:
        st.error(str(import_error))

    existing_rows = list(
        st.session_state.get(
            "bulk_match_rows",
            [],
        )
    )

    with st.expander(
        "Bulk add books",
        expanded=bool(existing_rows),
    ):
        st.write(
            "Paste one book per line using "
            "**Book title - Author**."
        )

        st.caption(
            "Nothing is added while you type or change matches. "
            "First press Find matches, check every result, then "
            "press Add matched books."
        )

        with st.form(
            "bulk_book_lookup_form",
            clear_on_submit=False,
        ):
            raw_books = st.text_area(
                "Books to find",
                key="bulk_book_input",
                height=220,
                placeholder=(
                    "Playground - Aron Beauregard\n"
                    "The Shining - Stephen King\n"
                    "Fourth Wing - Rebecca Yarros"
                ),
                help=(
                    f"Add up to {MAX_BULK_BOOKS} books "
                    "at a time."
                ),
            )

            find_matches = (
                st.form_submit_button(
                    "Find and match books",
                    type="primary",
                    use_container_width=True,
                )
            )

        if find_matches:
            parsed_books, parse_errors = (
                _parse_bulk_lines(raw_books)
            )

            st.session_state.bulk_match_parse_errors = (
                parse_errors
            )

            st.session_state.bulk_match_messages = []
            st.session_state.bulk_match_rows = []

            if not parsed_books:
                st.session_state.bulk_import_error = (
                    "No valid books were found. "
                    "Use one line per book as "
                    "Book title - Author."
                )
            else:
                rows: list[dict[str, Any]] = []
                all_messages: list[str] = []

                progress = st.progress(0.0)

                status = st.empty()

                for index, (
                    title,
                    author,
                ) in enumerate(parsed_books):
                    status.write(
                        f"Finding {index + 1} of "
                        f"{len(parsed_books)}: "
                        f"**{title}** by {author}"
                    )

                    candidates, messages = (
                        _search_bulk_candidates(
                            title,
                            author,
                        )
                    )

                    rows.append(
                        {
                            "requested_title": title,
                            "requested_author": author,
                            "candidates": [
                                candidate.to_dict()
                                for candidate in candidates
                            ],
                        }
                    )

                    all_messages.extend(messages)

                    progress.progress(
                        (index + 1)
                        / len(parsed_books)
                    )

                progress.empty()
                status.empty()

                next_token = int(
                    st.session_state.get(
                        "bulk_match_token",
                        0,
                    )
                ) + 1

                st.session_state.bulk_match_token = (
                    next_token
                )

                st.session_state.bulk_match_rows = (
                    rows
                )

                st.session_state.bulk_match_messages = list(
                    dict.fromkeys(all_messages)
                )[:8]

                existing_rows = rows

        for error_message in st.session_state.get(
            "bulk_match_parse_errors",
            [],
        ):
            st.warning(error_message)

        for catalogue_message in st.session_state.get(
            "bulk_match_messages",
            [],
        ):
            st.caption(catalogue_message)

        rows = list(
            st.session_state.get(
                "bulk_match_rows",
                existing_rows,
            )
        )

        if not rows:
            return

        matched_count = sum(
            bool(row.get("candidates"))
            for row in rows
        )

        st.markdown("### Check the matches")

        st.caption(
            f"Found catalogue choices for "
            f"{matched_count} of {len(rows)} books. "
            "Each line defaults to its strongest match."
        )

        token = int(
            st.session_state.get(
                "bulk_match_token",
                1,
            )
        )

        with st.form(
            f"bulk_book_match_form_{token}",
            clear_on_submit=False,
        ):
            default_shelf = st.selectbox(
                "Default shelf",
                DISPLAY_SHELVES,
                key=f"bulk_default_shelf_{token}",
                help=(
                    "You can override this separately "
                    "for any book below."
                ),
            )

            st.caption(
                f"Default selection: {default_shelf}"
            )

            for index, row in enumerate(rows):
                requested_title = str(
                    row.get("requested_title") or ""
                )

                requested_author = str(
                    row.get("requested_author") or ""
                )

                candidate_payloads = list(
                    row.get("candidates") or []
                )

                st.markdown(
                    f"**{index + 1}. "
                    f"{requested_title} — "
                    f"{requested_author}**"
                )

                if not candidate_payloads:
                    st.warning(
                        "No catalogue match was found. "
                        "This line will be skipped."
                    )
                    continue

                candidate_books = [
                    Book.from_dict(payload)
                    for payload in candidate_payloads
                ]

                option_labels = [
                    "Skip this book",
                    *[
                        _candidate_label(
                            candidate,
                            candidate_index,
                        )
                        for candidate_index, candidate
                        in enumerate(
                            candidate_books,
                            start=1,
                        )
                    ],
                ]

                match_column, shelf_column = (
                    st.columns(
                        [3.4, 1.2],
                        vertical_alignment="bottom",
                    )
                )

                with match_column:
                    st.selectbox(
                        "Exact catalogue match",
                        options=list(
                            range(
                                len(option_labels)
                            )
                        ),
                        index=1,
                        format_func=(
                            lambda selected,
                            labels=option_labels:
                            labels[selected]
                        ),
                        key=(
                            f"bulk_match_choice_"
                            f"{token}_{index}"
                        ),
                    )

                with shelf_column:
                    st.selectbox(
                        "Shelf",
                        PER_BOOK_SHELVES,
                        key=(
                            f"bulk_match_shelf_"
                            f"{token}_{index}"
                        ),
                    )

                preview_book = candidate_books[0]

                preview_parts: list[str] = []

                if preview_book.page_count:
                    preview_parts.append(
                        f"{preview_book.page_count:,} pages"
                    )

                if (
                    preview_book.average_rating
                    is not None
                ):
                    preview_parts.append(
                        f"★ "
                        f"{preview_book.average_rating:.1f}"
                    )

                if preview_parts:
                    st.caption(
                        "Top match: "
                        + " · ".join(preview_parts)
                    )

                st.divider()

            st.form_submit_button(
                "Add matched books",
                type="primary",
                use_container_width=True,
                disabled=matched_count == 0,
                on_click=_commit_bulk_import,
                args=(db, token),
            )
