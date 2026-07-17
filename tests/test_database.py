from bookverse.database import LibraryDatabase
from bookverse.models import Book


def _create_and_unlock(db: LibraryDatabase, username: str = "reader", pin: str = "1234") -> dict:
    profile = db.create_profile(
        username=username,
        display_name=username.title(),
        pin=pin,
        favourite_niches=["Horror", "Fantasy"],
        top_books=["The Shining"],
    )
    assert db.verify_profile_pin(profile["id"], pin)
    assert not db.verify_profile_pin(profile["id"], "wrong")
    db.set_active_user(profile["id"])
    return profile


def test_database_crud_and_backup(tmp_path) -> None:
    db = LibraryDatabase(tmp_path / "test.db")
    profile = _create_and_unlock(db)
    assert profile["favourite_niches"] == ["Horror", "Fantasy"]

    book = Book(source="test", source_id="1", title="A Book", authors=("Author",), page_count=200)
    db.save_entry(book, "Reading", user_rating=4.5, progress_pages=40)

    entries = db.list_entries("All")
    assert len(entries) == 1
    assert entries[0]["shelf"] == "Reading"
    assert entries[0]["progress_pages"] == 40

    db.update_entry(book.uid, "Finished", 5.0, "Excellent", 200)
    updated = db.list_entries("Finished")[0]
    assert updated["finished_at"]
    assert updated["review"] == "Excellent"

    backup = db.backup_payload()
    assert backup["format"] == "bookverse-backup-v2"
    assert backup["profile"]["top_books"] == ["The Shining"]

    other = LibraryDatabase(tmp_path / "restored.db")
    _create_and_unlock(other, "other", "5678")
    assert other.restore_payload(backup) == 1
    assert other.list_entries("Finished")[0]["book"].title == "A Book"

    db.remove_entry(book.uid)
    assert not db.list_entries("All")


def test_profiles_are_isolated(tmp_path) -> None:
    db = LibraryDatabase(tmp_path / "isolated.db")
    first = _create_and_unlock(db, "first", "1111")
    book = Book(source="test", source_id="shared", title="Shared Book")
    db.save_entry(book, "Favourites", user_rating=5.0)

    second = db.create_profile("second", "Second", "2222", ["Romance"], ["Jane Eyre"])
    db.set_active_user(second["id"])
    assert db.list_entries("All") == []
    db.save_entry(book, "Want to Read")
    assert db.list_entries("All")[0]["shelf"] == "Want to Read"

    db.set_active_user(first["id"])
    assert db.list_entries("All")[0]["shelf"] == "Favourites"


def test_first_profile_claims_legacy_library(tmp_path) -> None:
    import json
    import sqlite3
    from bookverse.database import utc_now

    path = tmp_path / "legacy.db"
    book = Book(source="legacy", source_id="1", title="Legacy Book")
    now = utc_now()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE books (
            uid TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE library_entries (
            uid TEXT PRIMARY KEY,
            shelf TEXT NOT NULL,
            user_rating REAL,
            review TEXT NOT NULL DEFAULT '',
            progress_pages INTEGER NOT NULL DEFAULT 0,
            started_at TEXT,
            finished_at TEXT,
            added_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(uid) REFERENCES books(uid) ON DELETE CASCADE
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO books VALUES (?, ?, ?, ?)",
        (book.uid, json.dumps(book.to_dict()), now, now),
    )
    conn.execute(
        "INSERT INTO library_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (book.uid, "Finished", 5.0, "Loved it", 0, None, now, now, now),
    )
    conn.execute("INSERT INTO settings VALUES ('annual_book_goal', '50')")
    conn.commit()
    conn.close()

    db = LibraryDatabase(path)
    profile = db.create_profile("legacyreader", "Legacy Reader", "1234")
    db.set_active_user(profile["id"])
    assert db.list_entries("All")[0]["book"].title == "Legacy Book"
    assert db.get_setting("annual_book_goal") == "50"
    db.remove_entry(book.uid)
    assert db.list_entries("All") == []


def test_delete_profile_requires_pin_and_cascades(tmp_path):
    from bookverse.database import LibraryDatabase
    from bookverse.models import Book

    db = LibraryDatabase(tmp_path / "delete_profile.db")
    profile = db.create_profile("reader", "Reader", "1234", top_books=[])
    db.set_active_user(profile["id"])
    book = Book(source="test", source_id="book", title="Test Book", authors=("A. Author",))
    db.save_entry(book, "Finished")

    try:
        db.delete_profile(profile["id"], "9999")
    except ValueError:
        pass
    else:
        raise AssertionError("Incorrect PIN should not delete a profile")

    assert db.get_profile(profile["id"]) is not None
    db.delete_profile(profile["id"], "1234")
    assert db.get_profile(profile["id"]) is None
    assert db.profile_count() == 0
