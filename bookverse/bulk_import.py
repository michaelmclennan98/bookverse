from __future__ import annotations

import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from typing import Any

import numpy as np
import streamlit as st
from PIL import Image

try:
    import zxingcpp
except ImportError:  # The main requirements install it; this keeps local source inspection safe.
    zxingcpp = None

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


def _normalise_isbn(value: str) -> str:
    return "".join(
        character.upper()
        for character in str(value)
        if character.isdigit() or character.upper() == "X"
    )


def _valid_isbn(value: str) -> bool:
    isbn = _normalise_isbn(value)
    if len(isbn) == 13 and isbn.isdigit():
        total = sum(
            int(character) * (1 if index % 2 == 0 else 3)
            for index, character in enumerate(isbn[:12])
        )
        return (10 - total % 10) % 10 == int(isbn[-1])
    if len(isbn) == 10 and isbn[:9].isdigit() and (isbn[-1].isdigit() or isbn[-1] == "X"):
        values = [int(character) for character in isbn[:9]]
        values.append(10 if isbn[-1] == "X" else int(isbn[-1]))
        return sum((10 - index) * number for index, number in enumerate(values)) % 11 == 0
    return False


def _decode_isbns_from_image(image_bytes: bytes) -> list[str]:
    if zxingcpp is None:
        raise RuntimeError("The barcode reader dependency is not installed.")
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise ValueError("The captured image could not be opened.") from exc

    detected: list[str] = []
    for barcode in zxingcpp.read_barcodes(np.asarray(image)):
        isbn = _normalise_isbn(getattr(barcode, "text", ""))
        if _valid_isbn(isbn) and isbn not in detected:
            detected.append(isbn)
    return detected


def _append_isbns_to_bulk_input(isbns: list[str]) -> None:
    existing = str(st.session_state.get("bulk_book_input", "")).strip()
    existing_lines = [line.strip() for line in existing.splitlines() if line.strip()]
    existing_isbns = {_normalise_isbn(line) for line in existing_lines}
    for isbn in isbns:
        if isbn not in existing_isbns:
            existing_lines.append(isbn)
            existing_isbns.add(isbn)
    st.session_state.bulk_book_input = "\n".join(existing_lines)


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

        compact_isbn = _normalise_isbn(line)
        if line.casefold().startswith("isbn") or len(compact_isbn) in {10, 13}:
            if _valid_isbn(compact_isbn):
                parsed.append((f"isbn:{compact_isbn}", ""))
                continue
            if len(compact_isbn) in {10, 13}:
                errors.append(f"Line {line_number}: the ISBN check digit is not valid.")
                continue

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
                f"Line {line_number}: use Book title - Author or enter an ISBN."
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


def _parse_csv_upload(data: bytes) -> tuple[list[tuple[str, str]], list[str]]:
    parsed: list[tuple[str, str]] = []
    errors: list[str] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")
    try:
        reader = csv.DictReader(io.StringIO(text))
    except csv.Error as exc:
        return [], [f"Could not read the CSV: {exc}"]
    if not reader.fieldnames:
        return [], ["The CSV does not contain column headings."]
    field_map = {str(name).strip().casefold(): name for name in reader.fieldnames if name}

    def first(row: dict[str, str], names: tuple[str, ...]) -> str:
        for name in names:
            original = field_map.get(name)
            if original and str(row.get(original) or "").strip():
                return str(row.get(original) or "").strip()
        return ""

    for row_number, row in enumerate(reader, start=2):
        title = first(row, ("title", "book title", "name"))
        author = first(row, ("author", "authors", "author name"))
        isbn = first(row, ("isbn", "isbn13", "isbn-13", "isbn10", "isbn-10"))
        if title and author:
            parsed.append((title, author))
        elif isbn:
            digits = _normalise_isbn(isbn)
            if _valid_isbn(digits):
                parsed.append((f"isbn:{digits}", ""))
            elif digits:
                errors.append(f"CSV row {row_number}: the ISBN check digit is not valid.")
        elif title:
            errors.append(f"CSV row {row_number}: author is missing for {title}.")
    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for title, author in parsed:
        key = (title.casefold(), author.casefold())
        if key not in seen:
            seen.add(key)
            deduped.append((title, author))
    if len(deduped) > MAX_BULK_BOOKS:
        errors.append(f"Only the first {MAX_BULK_BOOKS} CSV books were processed.")
    return deduped[:MAX_BULK_BOOKS], errors


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
    database_path: str = "",
) -> tuple[list[Book], list[str]]:
    settings = get_settings()
    is_isbn = title.casefold().startswith("isbn:")
    query = title.split(":", 1)[1] if is_isbn else title
    mode = "ISBN" if is_isbn else "Title"

    title_payloads, title_messages = cached_search(
        query,
        mode,
        "Auto",
        18,
        "",
        "relevance",
        "",
        settings.google_books_api_key,
        settings.open_library_contact,
        settings.request_timeout_seconds,
        0,
        database_path,
    )

    initial_books: list[Book] = []
    for payload in title_payloads:
        try:
            initial_books.append(Book.from_dict(payload))
        except (TypeError, ValueError, KeyError):
            continue
    initial_books.sort(key=lambda book: _candidate_score(title, author, book), reverse=True)
    strongest_score = _candidate_score(title, author, initial_books[0]) if initial_books else 0.0

    keyword_payloads: list[dict] = []
    keyword_messages: list[str] = []
    # Exact title + author or ISBN matches are accepted immediately. The second
    # provider pass is only used when the first pass is ambiguous.
    if not is_isbn and (len(initial_books) < 4 or strongest_score < 1.08):
        keyword_payloads, keyword_messages = cached_search(
            f"{title} {author}".strip(),
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
            database_path,
        )

    candidates: list[Book] = []
    seen_uids: set[str] = set()
    for payload in [*title_payloads, *keyword_payloads]:
        try:
            book = Book.from_dict(payload)
        except (TypeError, ValueError, KeyError):
            continue
        if book.uid in seen_uids:
            continue
        seen_uids.add(book.uid)
        candidates.append(book)
    candidates.sort(key=lambda book: _candidate_score(title, author, book), reverse=True)
    messages = list(dict.fromkeys([*title_messages, *keyword_messages]))
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
            "**Book title - Author** or an ISBN."
        )

        st.caption(
            "Nothing is added while you type or change matches. "
            "First press Find matches, check every result, then "
            "press Add matched books."
        )

        scan_left, scan_right = st.columns([2.2, 1], vertical_alignment="bottom")
        with scan_left:
            camera_image = st.camera_input(
                "Scan an ISBN barcode",
                key="bulk_barcode_camera",
                help="On a phone, photograph the barcode on the back of the book. The ISBN is staged for matching and is never added automatically.",
            )
        with scan_right:
            scan_pressed = st.button(
                "Read barcode",
                key="bulk_read_barcode",
                use_container_width=True,
                disabled=camera_image is None,
            )
        if scan_pressed and camera_image is not None:
            try:
                scanned_isbns = _decode_isbns_from_image(camera_image.getvalue())
            except (RuntimeError, ValueError) as exc:
                st.error(str(exc))
            else:
                if scanned_isbns:
                    _append_isbns_to_bulk_input(scanned_isbns)
                    st.success(
                        "Barcode read: "
                        + ", ".join(scanned_isbns)
                        + ". Check the list below, then press Find and match books."
                    )
                else:
                    st.warning("No valid ISBN barcode was found. Retake the photo close up, in focus and without glare.")

        csv_upload = st.file_uploader(
            "Optional CSV import",
            type=("csv",),
            key="bulk_csv_upload",
            help="Supports common Title, Author and ISBN columns from Goodreads, StoryGraph and spreadsheets.",
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
                    "9780307743657"
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
            parsed_books, parse_errors = _parse_bulk_lines(raw_books)
            if csv_upload is not None:
                csv_books, csv_errors = _parse_csv_upload(csv_upload.getvalue())
                parsed_books = [*parsed_books, *csv_books]
                parse_errors = [*parse_errors, *csv_errors]
                unique_books: list[tuple[str, str]] = []
                seen_books: set[tuple[str, str]] = set()
                for title, author in parsed_books:
                    key = (title.casefold(), author.casefold())
                    if key not in seen_books:
                        seen_books.add(key)
                        unique_books.append((title, author))
                parsed_books = unique_books[:MAX_BULK_BOOKS]

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
                rows_by_index: dict[int, dict[str, Any]] = {}
                all_messages: list[str] = []
                progress = st.progress(0.0)
                status = st.empty()
                database_path = str(getattr(db, "path", ""))

                def find_one(index: int, title: str, author: str):
                    candidates, messages = _search_bulk_candidates(title, author, database_path)
                    return index, title, author, candidates, messages

                completed = 0
                with ThreadPoolExecutor(max_workers=min(5, len(parsed_books)), thread_name_prefix="bookverse-bulk") as executor:
                    futures = [
                        executor.submit(find_one, index, title, author)
                        for index, (title, author) in enumerate(parsed_books)
                    ]
                    for future in as_completed(futures):
                        index, title, author, candidates, messages = future.result()
                        rows_by_index[index] = {
                            "requested_title": title,
                            "requested_author": author,
                            "candidates": [candidate.to_dict() for candidate in candidates],
                        }
                        all_messages.extend(messages)
                        completed += 1
                        status.write(f"Matched {completed} of {len(parsed_books)} books")
                        progress.progress(completed / len(parsed_books))

                progress.empty()
                status.empty()
                rows = [rows_by_index[index] for index in sorted(rows_by_index)]

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

                requested_label = (
                    requested_title.replace("isbn:", "ISBN ", 1)
                    if requested_title.casefold().startswith("isbn:")
                    else f"{requested_title} — {requested_author}"
                )
                st.markdown(f"**{index + 1}. {requested_label}**")

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
