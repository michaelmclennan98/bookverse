from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Book

DEFAULT_SHELVES = ("Want to Read", "Reading", "Finished", "DNF", "Favourites")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_string_list(values: list[str] | tuple[str, ...] | None, limit: int = 20) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        cleaned = " ".join(str(value).split()).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            output.append(cleaned)
            seen.add(key)
            if len(output) >= limit:
                break
    return output


def _hash_pin(pin: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 240_000)
    return salt.hex(), digest.hex()


class LibraryDatabase:
    """Local SQLite repository with isolated, PIN-locked user profiles."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.active_user_id: int | None = None
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS books (
                    uid TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    pin_salt TEXT NOT NULL,
                    pin_hash TEXT NOT NULL,
                    favourite_niches_json TEXT NOT NULL DEFAULT '[]',
                    top_books_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_library_entries (
                    user_id INTEGER NOT NULL,
                    uid TEXT NOT NULL,
                    shelf TEXT NOT NULL,
                    user_rating REAL,
                    review TEXT NOT NULL DEFAULT '',
                    progress_pages INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    finished_at TEXT,
                    added_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, uid),
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(uid) REFERENCES books(uid) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_user_library_shelf
                    ON user_library_entries(user_id, shelf);

                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY(user_id, key),
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS reading_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    uid TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    pages_read INTEGER NOT NULL DEFAULT 0,
                    minutes_read INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(uid) REFERENCES books(uid) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_reading_sessions_user_date
                    ON reading_sessions(user_id, session_date);

                CREATE TABLE IF NOT EXISTS journal_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    uid TEXT NOT NULL,
                    note_type TEXT NOT NULL DEFAULT 'Note',
                    note_text TEXT NOT NULL,
                    page_number INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(uid) REFERENCES books(uid) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_journal_notes_user_book
                    ON journal_notes(user_id, uid, created_at);

                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    user_id INTEGER NOT NULL,
                    uid TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    author TEXT NOT NULL DEFAULT '',
                    feedback TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, uid),
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS shortlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, name COLLATE NOCASE),
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS shortlist_items (
                    shortlist_id INTEGER NOT NULL,
                    uid TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(shortlist_id, uid),
                    FOREIGN KEY(shortlist_id) REFERENCES shortlists(id) ON DELETE CASCADE,
                    FOREIGN KEY(uid) REFERENCES books(uid) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS catalogue_cache (
                    cache_key TEXT PRIMARY KEY,
                    namespace TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    last_hit_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_catalogue_cache_expiry
                    ON catalogue_cache(expires_at);

                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    scan_type TEXT NOT NULL,
                    scan_mode TEXT NOT NULL,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    requests_count INTEGER NOT NULL DEFAULT 0,
                    cache_hits INTEGER NOT NULL DEFAULT 0,
                    result_count INTEGER NOT NULL DEFAULT 0,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES profiles(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_scan_history_user_created
                    ON scan_history(user_id, created_at);

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

            existing_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(user_library_entries)").fetchall()
            }
            migrations = {
                "format": "TEXT NOT NULL DEFAULT 'Unspecified'",
                "ownership": "TEXT NOT NULL DEFAULT 'Unspecified'",
                "audio_progress_minutes": "INTEGER NOT NULL DEFAULT 0",
                "reread_count": "INTEGER NOT NULL DEFAULT 0",
                "series_name": "TEXT NOT NULL DEFAULT ''",
                "series_number": "REAL",
                "personal_tags_json": "TEXT NOT NULL DEFAULT '[]'",
                "content_warnings_json": "TEXT NOT NULL DEFAULT '[]'",
            }
            for column_name, definition in migrations.items():
                if column_name not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE user_library_entries ADD COLUMN {column_name} {definition}"
                    )

            feedback_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(recommendation_feedback)").fetchall()
            }
            if "title" not in feedback_columns:
                conn.execute(
                    "ALTER TABLE recommendation_feedback ADD COLUMN title TEXT NOT NULL DEFAULT ''"
                )

    # ------------------------------------------------------------------
    # Profiles and local PIN lock
    # ------------------------------------------------------------------
    def profile_count(self) -> int:
        with self.connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0])

    def list_profiles(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, username, display_name, favourite_niches_json,
                       top_books_json, created_at, updated_at
                FROM profiles
                ORDER BY display_name COLLATE NOCASE, username COLLATE NOCASE
                """
            ).fetchall()
        return [self._profile_row(row) for row in rows]

    def get_profile(self, user_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, username, display_name, favourite_niches_json,
                       top_books_json, created_at, updated_at
                FROM profiles WHERE id = ?
                """,
                (int(user_id),),
            ).fetchone()
        return self._profile_row(row) if row else None

    def create_profile(
        self,
        username: str,
        display_name: str,
        pin: str,
        favourite_niches: list[str] | tuple[str, ...] | None = None,
        top_books: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        username = username.strip()
        display_name = display_name.strip() or username
        if len(username) < 2:
            raise ValueError("Username must contain at least 2 characters.")
        if not username.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username can contain letters, numbers, hyphens and underscores only.")
        if len(pin) < 4:
            raise ValueError("PIN must contain at least 4 characters.")

        niches = _normalise_string_list(list(favourite_niches or []), 20)
        books = _normalise_string_list(list(top_books or []), 12)
        salt, digest = _hash_pin(pin)
        now = utc_now()
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO profiles(
                        username, display_name, pin_salt, pin_hash,
                        favourite_niches_json, top_books_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        display_name,
                        salt,
                        digest,
                        json.dumps(niches, ensure_ascii=False),
                        json.dumps(books, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("That username already exists.") from exc
            user_id = int(cursor.lastrowid)
            self._claim_legacy_library(conn, user_id)

        profile = self.get_profile(user_id)
        if not profile:
            raise RuntimeError("Profile creation failed.")
        return profile

    def verify_profile_pin(self, user_id: int, pin: str) -> bool:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT pin_salt, pin_hash FROM profiles WHERE id = ?",
                (int(user_id),),
            ).fetchone()
        if not row:
            return False
        try:
            salt = bytes.fromhex(row["pin_salt"])
        except ValueError:
            return False
        _salt, candidate = _hash_pin(pin, salt)
        return hmac.compare_digest(candidate, row["pin_hash"])

    def update_profile_preferences(
        self,
        display_name: str,
        favourite_niches: list[str] | tuple[str, ...] | None,
        top_books: list[str] | tuple[str, ...] | None,
    ) -> None:
        user_id = self._require_user_id()
        name = display_name.strip()
        if not name:
            raise ValueError("Display name cannot be blank.")
        niches = _normalise_string_list(list(favourite_niches or []), 20)
        books = _normalise_string_list(list(top_books or []), 12)
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE profiles
                SET display_name=?, favourite_niches_json=?, top_books_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    name,
                    json.dumps(niches, ensure_ascii=False),
                    json.dumps(books, ensure_ascii=False),
                    utc_now(),
                    user_id,
                ),
            )

    def change_pin(self, current_pin: str, new_pin: str) -> None:
        user_id = self._require_user_id()
        if not self.verify_profile_pin(user_id, current_pin):
            raise ValueError("Current PIN is incorrect.")
        if len(new_pin) < 4:
            raise ValueError("New PIN must contain at least 4 characters.")
        salt, digest = _hash_pin(new_pin)
        with self.connection() as conn:
            conn.execute(
                "UPDATE profiles SET pin_salt=?, pin_hash=?, updated_at=? WHERE id=?",
                (salt, digest, utc_now(), user_id),
            )

    def delete_profile(self, user_id: int, pin: str) -> None:
        user_id = int(user_id)
        if not self.verify_profile_pin(user_id, pin):
            raise ValueError("Incorrect PIN. The profile was not deleted.")
        with self.connection() as conn:
            deleted = conn.execute("DELETE FROM profiles WHERE id = ?", (user_id,)).rowcount
            if not deleted:
                raise KeyError(f"Unknown profile: {user_id}")
            # Remove catalogue records no longer referenced by any profile.
            conn.execute(
                "DELETE FROM books WHERE uid NOT IN (SELECT DISTINCT uid FROM user_library_entries)"
            )
        if self.active_user_id == user_id:
            self.active_user_id = None

    def set_active_user(self, user_id: int | None) -> None:
        if user_id is None:
            self.active_user_id = None
            return
        if not self.get_profile(int(user_id)):
            raise KeyError(f"Unknown profile: {user_id}")
        self.active_user_id = int(user_id)

    def _profile_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "username": row["username"],
            "display_name": row["display_name"],
            "favourite_niches": json.loads(row["favourite_niches_json"] or "[]"),
            "top_books": json.loads(row["top_books_json"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _claim_legacy_library(self, conn: sqlite3.Connection, user_id: int) -> None:
        already = conn.execute(
            "SELECT value FROM app_meta WHERE key='legacy_library_claimed'"
        ).fetchone()
        if already:
            return
        legacy_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='library_entries'"
        ).fetchone()
        if legacy_table:
            rows = conn.execute(
                """
                SELECT uid, shelf, user_rating, review, progress_pages,
                       started_at, finished_at, added_at, updated_at
                FROM library_entries
                """
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO user_library_entries(
                        user_id, uid, shelf, user_rating, review, progress_pages,
                        started_at, finished_at, added_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        row["uid"],
                        row["shelf"],
                        row["user_rating"],
                        row["review"],
                        row["progress_pages"],
                        row["started_at"],
                        row["finished_at"],
                        row["added_at"],
                        row["updated_at"],
                    ),
                )
            # The legacy rows have now been transferred. Clear them so their old
            # foreign-key references cannot block normal per-profile deletion later.
            conn.execute("DELETE FROM library_entries")
        legacy_settings = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'"
        ).fetchone()
        if legacy_settings:
            for row in conn.execute("SELECT key, value FROM settings").fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO user_settings(user_id, key, value) VALUES (?, ?, ?)",
                    (user_id, row["key"], row["value"]),
                )
        conn.execute(
            "INSERT OR REPLACE INTO app_meta(key, value) VALUES ('legacy_library_claimed', ?)",
            (str(user_id),),
        )

    def _require_user_id(self) -> int:
        if self.active_user_id is None:
            raise RuntimeError("No BookVerse profile is unlocked.")
        return int(self.active_user_id)

    # ------------------------------------------------------------------
    # User library
    # ------------------------------------------------------------------
    def save_entry(
        self,
        book: Book,
        shelf: str,
        user_rating: float | None = None,
        review: str = "",
        progress_pages: int = 0,
    ) -> None:
        user_id = self._require_user_id()
        shelf = shelf.strip() or "Want to Read"
        now = utc_now()
        started_at = now if shelf == "Reading" else None
        finished_at = now if shelf == "Finished" else None
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO books(uid, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (book.uid, json.dumps(book.to_dict(), ensure_ascii=False), now, now),
            )
            existing = conn.execute(
                """
                SELECT started_at, finished_at, added_at
                FROM user_library_entries WHERE user_id=? AND uid=?
                """,
                (user_id, book.uid),
            ).fetchone()
            if existing:
                started_at = existing["started_at"] or started_at
                finished_at = existing["finished_at"] or finished_at
                added_at = existing["added_at"]
            else:
                added_at = now
            conn.execute(
                """
                INSERT INTO user_library_entries(
                    user_id, uid, shelf, user_rating, review, progress_pages,
                    started_at, finished_at, added_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, uid) DO UPDATE SET
                    shelf=excluded.shelf,
                    user_rating=COALESCE(excluded.user_rating, user_library_entries.user_rating),
                    review=CASE WHEN excluded.review != '' THEN excluded.review ELSE user_library_entries.review END,
                    progress_pages=excluded.progress_pages,
                    started_at=COALESCE(user_library_entries.started_at, excluded.started_at),
                    finished_at=CASE
                        WHEN excluded.shelf = 'Finished' THEN COALESCE(user_library_entries.finished_at, excluded.finished_at)
                        WHEN excluded.shelf != 'Finished' THEN NULL
                        ELSE user_library_entries.finished_at
                    END,
                    updated_at=excluded.updated_at
                """,
                (
                    user_id,
                    book.uid,
                    shelf,
                    user_rating,
                    review.strip(),
                    max(0, progress_pages),
                    started_at,
                    finished_at,
                    added_at,
                    now,
                ),
            )

    def update_entry(
        self,
        uid: str,
        shelf: str,
        user_rating: float | None,
        review: str,
        progress_pages: int,
    ) -> None:
        user_id = self._require_user_id()
        now = utc_now()
        with self.connection() as conn:
            current = conn.execute(
                """
                SELECT shelf, started_at, finished_at FROM user_library_entries
                WHERE user_id=? AND uid=?
                """,
                (user_id, uid),
            ).fetchone()
            if not current:
                raise KeyError(f"Unknown library entry: {uid}")
            started_at = current["started_at"] or (now if shelf == "Reading" else None)
            finished_at = current["finished_at"]
            if shelf == "Finished" and not finished_at:
                finished_at = now
            elif shelf != "Finished":
                finished_at = None
            conn.execute(
                """
                UPDATE user_library_entries
                SET shelf=?, user_rating=?, review=?, progress_pages=?,
                    started_at=?, finished_at=?, updated_at=?
                WHERE user_id=? AND uid=?
                """,
                (
                    shelf.strip() or "Want to Read",
                    user_rating,
                    review.strip(),
                    max(0, int(progress_pages)),
                    started_at,
                    finished_at,
                    now,
                    user_id,
                    uid,
                ),
            )

    def remove_entry(self, uid: str) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute("DELETE FROM reading_sessions WHERE user_id=? AND uid=?", (user_id, uid))
            conn.execute("DELETE FROM journal_notes WHERE user_id=? AND uid=?", (user_id, uid))
            conn.execute("DELETE FROM recommendation_feedback WHERE user_id=? AND uid=?", (user_id, uid))
            conn.execute(
                """
                DELETE FROM shortlist_items
                WHERE uid=? AND shortlist_id IN (SELECT id FROM shortlists WHERE user_id=?)
                """,
                (uid, user_id),
            )
            conn.execute(
                "DELETE FROM user_library_entries WHERE user_id=? AND uid=?",
                (user_id, uid),
            )
            still_used = conn.execute(
                "SELECT 1 FROM user_library_entries WHERE uid=? LIMIT 1", (uid,)
            ).fetchone()
            if not still_used:
                conn.execute("DELETE FROM books WHERE uid=?", (uid,))

    def list_entries(self, shelf: str = "All") -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        sql = """
            SELECT b.payload_json, e.uid, e.shelf, e.user_rating, e.review,
                   e.progress_pages, e.started_at, e.finished_at, e.added_at, e.updated_at,
                   e.format, e.ownership, e.audio_progress_minutes, e.reread_count,
                   e.series_name, e.series_number, e.personal_tags_json,
                   e.content_warnings_json
            FROM user_library_entries e
            JOIN books b ON b.uid = e.uid
            WHERE e.user_id = ?
        """
        params: list[Any] = [user_id]
        if shelf != "All":
            sql += " AND e.shelf = ?"
            params.append(shelf)
        sql += " ORDER BY e.updated_at DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "book": Book.from_dict(json.loads(row["payload_json"])),
                    "uid": row["uid"],
                    "shelf": row["shelf"],
                    "user_rating": row["user_rating"],
                    "review": row["review"],
                    "progress_pages": row["progress_pages"],
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
                    "added_at": row["added_at"],
                    "updated_at": row["updated_at"],
                    "format": row["format"] or "Unspecified",
                    "ownership": row["ownership"] or "Unspecified",
                    "audio_progress_minutes": int(row["audio_progress_minutes"] or 0),
                    "reread_count": int(row["reread_count"] or 0),
                    "series_name": row["series_name"] or "",
                    "series_number": row["series_number"],
                    "personal_tags": json.loads(row["personal_tags_json"] or "[]"),
                    "content_warnings": json.loads(row["content_warnings_json"] or "[]"),
                }
            )
        return output

    def shelves(self) -> list[str]:
        user_id = self._require_user_id()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT shelf FROM user_library_entries
                WHERE user_id=? ORDER BY shelf
                """,
                (user_id,),
            ).fetchall()
        custom = [row["shelf"] for row in rows]
        return list(dict.fromkeys([*DEFAULT_SHELVES, *custom]))

    def get_setting(self, key: str, default: str = "") -> str:
        user_id = self._require_user_id()
        with self.connection() as conn:
            row = conn.execute(
                "SELECT value FROM user_settings WHERE user_id=? AND key=?",
                (user_id, key),
            ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_settings(user_id, key, value) VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value
                """,
                (user_id, key, value),
            )

    def get_entry(self, uid: str) -> dict[str, Any] | None:
        return next((entry for entry in self.list_entries("All") if entry["uid"] == uid), None)

    def update_entry_metadata(
        self,
        uid: str,
        *,
        format_name: str = "Unspecified",
        ownership: str = "Unspecified",
        audio_progress_minutes: int = 0,
        reread_count: int = 0,
        series_name: str = "",
        series_number: float | None = None,
        personal_tags: list[str] | tuple[str, ...] | None = None,
        content_warnings: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        user_id = self._require_user_id()
        tags = _normalise_string_list(list(personal_tags or []), 30)
        warnings = _normalise_string_list(list(content_warnings or []), 30)
        with self.connection() as conn:
            updated = conn.execute(
                """
                UPDATE user_library_entries
                SET format=?, ownership=?, audio_progress_minutes=?, reread_count=?,
                    series_name=?, series_number=?, personal_tags_json=?,
                    content_warnings_json=?, updated_at=?
                WHERE user_id=? AND uid=?
                """,
                (
                    format_name.strip() or "Unspecified",
                    ownership.strip() or "Unspecified",
                    max(0, int(audio_progress_minutes)),
                    max(0, int(reread_count)),
                    series_name.strip(),
                    series_number,
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    utc_now(),
                    user_id,
                    uid,
                ),
            ).rowcount
            if not updated:
                raise KeyError(f"Unknown library entry: {uid}")

    def add_reading_session(
        self,
        uid: str,
        session_date: str,
        pages_read: int = 0,
        minutes_read: int = 0,
        notes: str = "",
    ) -> int:
        user_id = self._require_user_id()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO reading_sessions(
                    user_id, uid, session_date, pages_read, minutes_read, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    uid,
                    session_date.strip() or utc_now()[:10],
                    max(0, int(pages_read)),
                    max(0, int(minutes_read)),
                    notes.strip(),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_reading_sessions(self, uid: str | None = None) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        sql = """
            SELECT id, uid, session_date, pages_read, minutes_read, notes, created_at
            FROM reading_sessions WHERE user_id=?
        """
        params: list[Any] = [user_id]
        if uid:
            sql += " AND uid=?"
            params.append(uid)
        sql += " ORDER BY session_date DESC, id DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def add_journal_note(
        self,
        uid: str,
        note_text: str,
        note_type: str = "Note",
        page_number: int | None = None,
    ) -> int:
        user_id = self._require_user_id()
        cleaned = note_text.strip()
        if not cleaned:
            raise ValueError("Journal text cannot be blank.")
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO journal_notes(
                    user_id, uid, note_type, note_text, page_number, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    uid,
                    note_type.strip() or "Note",
                    cleaned,
                    max(0, int(page_number)) if page_number is not None else None,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def list_journal_notes(self, uid: str | None = None) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        sql = """
            SELECT id, uid, note_type, note_text, page_number, created_at
            FROM journal_notes WHERE user_id=?
        """
        params: list[Any] = [user_id]
        if uid:
            sql += " AND uid=?"
            params.append(uid)
        sql += " ORDER BY created_at DESC, id DESC"
        with self.connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def delete_journal_note(self, note_id: int) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM journal_notes WHERE id=? AND user_id=?",
                (int(note_id), user_id),
            )

    def set_recommendation_feedback(self, book: Book, feedback: str) -> None:
        user_id = self._require_user_id()
        now = utc_now()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO recommendation_feedback(
                    user_id, uid, title, author, feedback, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, uid) DO UPDATE SET
                    title=excluded.title,
                    author=excluded.author,
                    feedback=excluded.feedback,
                    updated_at=excluded.updated_at
                """,
                (user_id, book.uid, book.display_title, book.author_text, feedback.strip(), now, now),
            )

    def list_recommendation_feedback(self) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT uid, title, author, feedback, created_at, updated_at
                FROM recommendation_feedback
                WHERE user_id=? ORDER BY updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_recommendation_feedback(self, uid: str) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM recommendation_feedback WHERE user_id=? AND uid=?",
                (user_id, str(uid)),
            )

    def clear_recommendation_feedback(self) -> int:
        user_id = self._require_user_id()
        with self.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM recommendation_feedback WHERE user_id=?",
                (user_id,),
            )
        return int(cursor.rowcount or 0)

    def create_shortlist(self, name: str) -> int:
        user_id = self._require_user_id()
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Shortlist name cannot be blank.")
        with self.connection() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO shortlists(user_id, name, created_at) VALUES (?, ?, ?)",
                    (user_id, cleaned, utc_now()),
                )
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT id FROM shortlists WHERE user_id=? AND name=? COLLATE NOCASE",
                    (user_id, cleaned),
                ).fetchone()
                return int(row["id"]) if row else 0
            return int(cursor.lastrowid)

    def list_shortlists(self) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.name, s.created_at, COUNT(si.uid) AS book_count
                FROM shortlists s
                LEFT JOIN shortlist_items si ON si.shortlist_id=s.id
                WHERE s.user_id=?
                GROUP BY s.id
                ORDER BY s.name COLLATE NOCASE
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_to_shortlist(self, shortlist_id: int, uid: str) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            owns = conn.execute(
                "SELECT 1 FROM shortlists WHERE id=? AND user_id=?",
                (int(shortlist_id), user_id),
            ).fetchone()
            if not owns:
                raise KeyError("Unknown shortlist.")
            conn.execute(
                "INSERT OR IGNORE INTO shortlist_items(shortlist_id, uid, added_at) VALUES (?, ?, ?)",
                (int(shortlist_id), uid, utc_now()),
            )

    def remove_from_shortlist(self, shortlist_id: int, uid: str) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute(
                """
                DELETE FROM shortlist_items
                WHERE shortlist_id=? AND uid=? AND shortlist_id IN (
                    SELECT id FROM shortlists WHERE user_id=?
                )
                """,
                (int(shortlist_id), uid, user_id),
            )

    def shortlist_books(self, shortlist_id: int) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT b.payload_json, si.uid, si.added_at
                FROM shortlist_items si
                JOIN shortlists s ON s.id=si.shortlist_id
                JOIN books b ON b.uid=si.uid
                WHERE si.shortlist_id=? AND s.user_id=?
                ORDER BY si.added_at DESC
                """,
                (int(shortlist_id), user_id),
            ).fetchall()
        return [
            {"book": Book.from_dict(json.loads(row["payload_json"])), "uid": row["uid"], "added_at": row["added_at"]}
            for row in rows
        ]

    def delete_shortlist(self, shortlist_id: int) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute("DELETE FROM shortlists WHERE id=? AND user_id=?", (int(shortlist_id), user_id))

    def series_summary(self) -> list[dict[str, Any]]:
        entries = [entry for entry in self.list_entries("All") if entry.get("series_name")]
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            grouped.setdefault(str(entry["series_name"]), []).append(entry)
        output: list[dict[str, Any]] = []
        for name, values in sorted(grouped.items(), key=lambda item: item[0].casefold()):
            ordered = sorted(
                values,
                key=lambda entry: (
                    float(entry["series_number"]) if entry.get("series_number") is not None else 9999,
                    entry["book"].title.casefold(),
                ),
            )
            finished = sum(entry["shelf"] == "Finished" for entry in ordered)
            next_entry = next((entry for entry in ordered if entry["shelf"] != "Finished"), None)
            output.append(
                {
                    "name": name,
                    "books": ordered,
                    "finished": finished,
                    "total": len(ordered),
                    "next": next_entry,
                }
            )
        return output

    def duplicate_groups(self) -> list[list[dict[str, Any]]]:
        def normalise(value: str) -> str:
            return " ".join("".join(ch if ch.isalnum() else " " for ch in value.casefold()).split())
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in self.list_entries("All"):
            book = entry["book"]
            if book.primary_isbn:
                key = f"isbn:{''.join(ch for ch in book.primary_isbn if ch.isdigit())}"
            else:
                key = f"work:{normalise(book.title)}|{normalise(book.author_text)}"
            grouped.setdefault(key, []).append(entry)
        return [values for values in grouped.values() if len(values) > 1]

    def merge_duplicate_entries(self, preferred_uid: str, duplicate_uids: list[str]) -> int:
        """Merge duplicate editions into one preferred library record without losing reader data."""
        user_id = self._require_user_id()
        ordered_uids = [preferred_uid, *duplicate_uids]
        unique_uids: list[str] = []
        for uid in ordered_uids:
            cleaned = str(uid).strip()
            if cleaned and cleaned not in unique_uids:
                unique_uids.append(cleaned)
        if preferred_uid not in unique_uids or len(unique_uids) < 2:
            return 0

        placeholders = ",".join("?" for _ in unique_uids)
        with self.connection() as conn:
            rows = conn.execute(
                f"""
                SELECT uid, shelf, user_rating, review, progress_pages, started_at,
                       finished_at, added_at, format, ownership, audio_progress_minutes,
                       reread_count, series_name, series_number, personal_tags_json,
                       content_warnings_json
                FROM user_library_entries
                WHERE user_id=? AND uid IN ({placeholders})
                """,
                (user_id, *unique_uids),
            ).fetchall()
            row_map = {str(row["uid"]): row for row in rows}
            preferred = row_map.get(preferred_uid)
            if preferred is None:
                raise KeyError("The preferred edition is not in this profile's library.")
            duplicates = [row_map[uid] for uid in unique_uids if uid != preferred_uid and uid in row_map]
            if not duplicates:
                return 0
            all_rows = [preferred, *duplicates]

            shelf_priority = {"Finished": 5, "Reading": 4, "Favourites": 3, "Want to Read": 2, "DNF": 1}
            shelf = max(all_rows, key=lambda row: shelf_priority.get(str(row["shelf"]), 0))["shelf"]
            ratings = [float(row["user_rating"]) for row in all_rows if row["user_rating"] is not None]
            rating = preferred["user_rating"] if preferred["user_rating"] is not None else (max(ratings) if ratings else None)
            reviews: list[str] = []
            for row in all_rows:
                review = str(row["review"] or "").strip()
                if review and review not in reviews:
                    reviews.append(review)
            progress = max(int(row["progress_pages"] or 0) for row in all_rows)
            audio_progress = max(int(row["audio_progress_minutes"] or 0) for row in all_rows)
            rereads = max(int(row["reread_count"] or 0) for row in all_rows)
            started_values = [str(row["started_at"]) for row in all_rows if row["started_at"]]
            finished_values = [str(row["finished_at"]) for row in all_rows if row["finished_at"]]
            added_values = [str(row["added_at"]) for row in all_rows if row["added_at"]]

            def first_meaningful(column: str, blank_values: set[object]) -> object:
                for row in all_rows:
                    value = row[column]
                    if value not in blank_values:
                        return value
                return preferred[column]

            tags: list[str] = []
            warnings: list[str] = []
            for row in all_rows:
                for target, column in ((tags, "personal_tags_json"), (warnings, "content_warnings_json")):
                    try:
                        values = json.loads(row[column] or "[]")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        values = []
                    for value in values:
                        cleaned = str(value).strip()
                        if cleaned and cleaned.casefold() not in {item.casefold() for item in target}:
                            target.append(cleaned)

            conn.execute(
                """
                UPDATE user_library_entries
                SET shelf=?, user_rating=?, review=?, progress_pages=?, started_at=?,
                    finished_at=?, added_at=?, updated_at=?, format=?, ownership=?,
                    audio_progress_minutes=?, reread_count=?, series_name=?, series_number=?,
                    personal_tags_json=?, content_warnings_json=?
                WHERE user_id=? AND uid=?
                """,
                (
                    shelf,
                    rating,
                    "\n\n".join(reviews),
                    progress,
                    min(started_values) if started_values else None,
                    max(finished_values) if shelf == "Finished" and finished_values else (utc_now() if shelf == "Finished" else None),
                    min(added_values) if added_values else utc_now(),
                    utc_now(),
                    first_meaningful("format", {None, "", "Unspecified"}),
                    first_meaningful("ownership", {None, "", "Unspecified"}),
                    audio_progress,
                    rereads,
                    first_meaningful("series_name", {None, ""}),
                    first_meaningful("series_number", {None, 0, 0.0}),
                    json.dumps(tags, ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    user_id,
                    preferred_uid,
                ),
            )

            duplicate_ids = [str(row["uid"]) for row in duplicates]
            duplicate_placeholders = ",".join("?" for _ in duplicate_ids)
            conn.execute(
                f"UPDATE reading_sessions SET uid=? WHERE user_id=? AND uid IN ({duplicate_placeholders})",
                (preferred_uid, user_id, *duplicate_ids),
            )
            conn.execute(
                f"UPDATE journal_notes SET uid=? WHERE user_id=? AND uid IN ({duplicate_placeholders})",
                (preferred_uid, user_id, *duplicate_ids),
            )
            conn.execute(
                f"""
                INSERT OR IGNORE INTO shortlist_items(shortlist_id, uid, added_at)
                SELECT shortlist_id, ?, MIN(added_at)
                FROM shortlist_items
                WHERE uid IN ({duplicate_placeholders})
                GROUP BY shortlist_id
                """,
                (preferred_uid, *duplicate_ids),
            )
            conn.execute(
                f"DELETE FROM shortlist_items WHERE uid IN ({duplicate_placeholders})",
                tuple(duplicate_ids),
            )
            feedback = conn.execute(
                f"""
                SELECT title, author, feedback, created_at, updated_at
                FROM recommendation_feedback
                WHERE user_id=? AND uid IN ({duplicate_placeholders})
                ORDER BY updated_at DESC LIMIT 1
                """,
                (user_id, *duplicate_ids),
            ).fetchone()
            if feedback:
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback(user_id, uid, title, author, feedback, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, uid) DO UPDATE SET
                        title=excluded.title, author=excluded.author,
                        feedback=excluded.feedback, updated_at=excluded.updated_at
                    """,
                    (
                        user_id,
                        preferred_uid,
                        feedback["title"],
                        feedback["author"],
                        feedback["feedback"],
                        feedback["created_at"],
                        feedback["updated_at"],
                    ),
                )
            conn.execute(
                f"DELETE FROM recommendation_feedback WHERE user_id=? AND uid IN ({duplicate_placeholders})",
                (user_id, *duplicate_ids),
            )
            conn.execute(
                f"DELETE FROM user_library_entries WHERE user_id=? AND uid IN ({duplicate_placeholders})",
                (user_id, *duplicate_ids),
            )
            for uid in duplicate_ids:
                still_used = conn.execute(
                    "SELECT 1 FROM user_library_entries WHERE uid=? LIMIT 1",
                    (uid,),
                ).fetchone()
                if not still_used:
                    conn.execute("DELETE FROM books WHERE uid=?", (uid,))
        return len(duplicates)


    def add_scan_history(
        self,
        scan_type: str,
        scan_mode: str,
        duration_seconds: float,
        requests_count: int,
        cache_hits: int,
        result_count: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        user_id = self._require_user_id()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO scan_history(
                    user_id, scan_type, scan_mode, duration_seconds, requests_count,
                    cache_hits, result_count, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    scan_type,
                    scan_mode,
                    max(0.0, float(duration_seconds)),
                    max(0, int(requests_count)),
                    max(0, int(cache_hits)),
                    max(0, int(result_count)),
                    json.dumps(details or {}, ensure_ascii=False),
                    utc_now(),
                ),
            )

    def list_scan_history(self, limit: int = 20) -> list[dict[str, Any]]:
        user_id = self._require_user_id()
        with self.connection() as conn:
            rows = conn.execute(
                """
                SELECT scan_type, scan_mode, duration_seconds, requests_count,
                       cache_hits, result_count, details_json, created_at
                FROM scan_history WHERE user_id=?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, max(1, int(limit))),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json") or "{}")
            output.append(item)
        return output

    def backup_payload(self) -> dict[str, Any]:
        profile = self.get_profile(self._require_user_id()) or {}
        entries = self.list_entries("All")
        return {
            "format": "bookverse-backup-v3",
            "created_at": utc_now(),
            "profile": {
                "display_name": profile.get("display_name", ""),
                "favourite_niches": profile.get("favourite_niches", []),
                "top_books": profile.get("top_books", []),
            },
            "entries": [
                {
                    "book": entry["book"].to_dict(),
                    "shelf": entry["shelf"],
                    "user_rating": entry["user_rating"],
                    "review": entry["review"],
                    "progress_pages": entry["progress_pages"],
                    "format": entry.get("format", "Unspecified"),
                    "ownership": entry.get("ownership", "Unspecified"),
                    "audio_progress_minutes": entry.get("audio_progress_minutes", 0),
                    "reread_count": entry.get("reread_count", 0),
                    "series_name": entry.get("series_name", ""),
                    "series_number": entry.get("series_number"),
                    "personal_tags": entry.get("personal_tags", []),
                    "content_warnings": entry.get("content_warnings", []),
                }
                for entry in entries
            ],
            "reading_sessions": self.list_reading_sessions(),
            "journal_notes": self.list_journal_notes(),
            "recommendation_feedback": self.list_recommendation_feedback(),
            "shortlists": [
                {
                    **shortlist,
                    "uids": [item["uid"] for item in self.shortlist_books(int(shortlist["id"]))],
                }
                for shortlist in self.list_shortlists()
            ],
        }

    def restore_payload(self, payload: dict[str, Any]) -> int:
        supported = {"bookverse-backup-v1", "bookverse-backup-v2", "bookverse-backup-v3"}
        if payload.get("format") not in supported:
            raise ValueError("This is not a supported BookVerse backup.")
        profile_payload = payload.get("profile") or {}
        if payload.get("format") in {"bookverse-backup-v2", "bookverse-backup-v3"} and profile_payload:
            current = self.get_profile(self._require_user_id()) or {}
            self.update_profile_preferences(
                profile_payload.get("display_name") or current.get("display_name") or "BookVerse User",
                profile_payload.get("favourite_niches") or current.get("favourite_niches") or [],
                profile_payload.get("top_books") or current.get("top_books") or [],
            )
        count = 0
        for item in payload.get("entries") or []:
            book = Book.from_dict(item["book"])
            self.save_entry(
                book,
                shelf=item.get("shelf") or "Want to Read",
                user_rating=item.get("user_rating"),
                review=item.get("review") or "",
                progress_pages=int(item.get("progress_pages") or 0),
            )
            if payload.get("format") == "bookverse-backup-v3":
                self.update_entry_metadata(
                    book.uid,
                    format_name=item.get("format") or "Unspecified",
                    ownership=item.get("ownership") or "Unspecified",
                    audio_progress_minutes=int(item.get("audio_progress_minutes") or 0),
                    reread_count=int(item.get("reread_count") or 0),
                    series_name=item.get("series_name") or "",
                    series_number=item.get("series_number"),
                    personal_tags=item.get("personal_tags") or [],
                    content_warnings=item.get("content_warnings") or [],
                )
            count += 1
        if payload.get("format") == "bookverse-backup-v3":
            known_uids = {entry["uid"] for entry in self.list_entries("All")}
            for session in payload.get("reading_sessions") or []:
                if session.get("uid") in known_uids:
                    self.add_reading_session(
                        session["uid"],
                        session.get("session_date") or utc_now()[:10],
                        int(session.get("pages_read") or 0),
                        int(session.get("minutes_read") or 0),
                        session.get("notes") or "",
                    )
            for note in payload.get("journal_notes") or []:
                if note.get("uid") in known_uids:
                    self.add_journal_note(
                        note["uid"],
                        note.get("note_text") or "",
                        note.get("note_type") or "Note",
                        note.get("page_number"),
                    )
            entry_map = {entry["uid"]: entry["book"] for entry in self.list_entries("All")}
            for feedback in payload.get("recommendation_feedback") or []:
                uid = str(feedback.get("uid") or "")
                if uid in entry_map:
                    self.set_recommendation_feedback(entry_map[uid], feedback.get("feedback") or "Interested")
            for shortlist in payload.get("shortlists") or []:
                shortlist_id = self.create_shortlist(shortlist.get("name") or "Imported shortlist")
                for uid in shortlist.get("uids") or []:
                    if uid in known_uids:
                        self.add_to_shortlist(shortlist_id, uid)
        return count

