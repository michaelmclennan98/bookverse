from __future__ import annotations

from pathlib import Path

from bookverse.database import LibraryDatabase
from bookverse.models import Book
from bookverse.persistent_cache import cache_stats, get_cached, set_cached


def _db(tmp_path) -> LibraryDatabase:
    db = LibraryDatabase(tmp_path / "v20.db")
    profile = db.create_profile("reader", "Reader", "1234")
    db.set_active_user(profile["id"])
    return db


def test_tracking_journal_series_feedback_and_shortlists(tmp_path) -> None:
    db = _db(tmp_path)
    book = Book(source="test", source_id="one", title="Series Book", authors=("Writer",), page_count=300)
    db.save_entry(book, "Reading", progress_pages=20)
    db.update_entry_metadata(
        book.uid,
        format_name="Hardback",
        ownership="Owned",
        series_name="A Series",
        series_number=2,
        personal_tags=["autumn", "book club"],
        content_warnings=["violence"],
    )
    db.add_reading_session(book.uid, "2026-07-28", pages_read=25, minutes_read=45, notes="Good pace")
    db.add_journal_note(book.uid, "A useful quotation", "Quote", 45)
    db.set_recommendation_feedback(book, "More like this")
    shortlist_id = db.create_shortlist("Next up")
    db.add_to_shortlist(shortlist_id, book.uid)

    entry = db.get_entry(book.uid)
    assert entry is not None
    assert entry["format"] == "Hardback"
    assert entry["series_name"] == "A Series"
    assert entry["personal_tags"] == ["autumn", "book club"]
    assert db.list_reading_sessions(book.uid)[0]["minutes_read"] == 45
    assert db.list_journal_notes(book.uid)[0]["note_type"] == "Quote"
    assert db.list_recommendation_feedback()[0]["feedback"] == "More like this"
    assert db.shortlist_books(shortlist_id)[0]["uid"] == book.uid
    assert db.series_summary()[0]["name"] == "A Series"


def test_persistent_catalogue_cache_roundtrip(tmp_path) -> None:
    path = tmp_path / "cache.db"
    set_cached(path, "search", ("query",), {"books": [1]}, 3600)
    assert get_cached(path, "search", "query") == {"books": [1]}
    stats = cache_stats(path)
    assert stats["entries"] == 1
    assert stats["hits"] == 1


def test_manual_recommendations_and_feature_modules_are_wired() -> None:
    root = Path(__file__).resolve().parents[1]
    views = (root / "bookverse" / "views.py").read_text(encoding="utf-8")
    cache = (root / "bookverse" / "cache.py").read_text(encoding="utf-8")
    bulk = (root / "bookverse" / "bulk_import.py").read_text(encoding="utf-8")
    assert "personalised_last_results_v20" in views
    assert "manual_personalised_scan" in views
    assert "render_mood_finder" in views
    assert "render_library_tools" in views
    assert "render_entry_tracking" in views
    assert "ThreadPoolExecutor" in cache
    assert "scan_mode" in cache
    assert "ThreadPoolExecutor" in bulk
    assert "Optional CSV import" in bulk
    assert "ISBN" in bulk
    assert "st.camera_input" in bulk
    assert "_decode_isbns_from_image" in bulk


def test_duplicate_merge_preserves_reader_data(tmp_path) -> None:
    db = _db(tmp_path)
    first = Book(source="google", source_id="one", title="The Same Book", authors=("A. Writer",), page_count=300)
    second = Book(source="openlibrary", source_id="two", title="The Same Book", authors=("A. Writer",), page_count=320)
    db.save_entry(first, "Want to Read", user_rating=4.0, review="First note", progress_pages=10)
    db.save_entry(second, "Finished", user_rating=5.0, review="Second note", progress_pages=320)
    db.update_entry_metadata(first.uid, format_name="Hardback", personal_tags=["keeper"])
    db.update_entry_metadata(second.uid, ownership="Owned", series_name="Same Series", series_number=1)
    db.add_reading_session(second.uid, "2026-07-28", pages_read=40, minutes_read=60)
    db.add_journal_note(second.uid, "Remember this", "Note", 100)
    shortlist_id = db.create_shortlist("Compare")
    db.add_to_shortlist(shortlist_id, second.uid)
    db.set_recommendation_feedback(second, "More intense")

    assert len(db.duplicate_groups()) == 1
    assert db.merge_duplicate_entries(first.uid, [second.uid]) == 1

    entries = db.list_entries("All")
    assert len(entries) == 1
    merged = entries[0]
    assert merged["uid"] == first.uid
    assert merged["shelf"] == "Finished"
    assert merged["progress_pages"] == 320
    assert merged["user_rating"] == 4.0  # Preferred edition's explicit rating wins.
    assert "First note" in merged["review"] and "Second note" in merged["review"]
    assert merged["format"] == "Hardback"
    assert merged["ownership"] == "Owned"
    assert merged["series_name"] == "Same Series"
    assert db.list_reading_sessions(first.uid)[0]["minutes_read"] == 60
    assert db.list_journal_notes(first.uid)[0]["note_text"] == "Remember this"
    assert db.shortlist_books(shortlist_id)[0]["uid"] == first.uid
    feedback = db.list_recommendation_feedback()[0]
    assert feedback["uid"] == first.uid
    assert feedback["title"] == second.display_title
