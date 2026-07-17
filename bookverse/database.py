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

                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
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
                   e.progress_pages, e.started_at, e.finished_at, e.added_at, e.updated_at
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

    def backup_payload(self) -> dict[str, Any]:
        profile = self.get_profile(self._require_user_id()) or {}
        entries = self.list_entries("All")
        return {
            "format": "bookverse-backup-v2",
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
                }
                for entry in entries
            ],
        }

    def restore_payload(self, payload: dict[str, Any]) -> int:
        if payload.get("format") not in {"bookverse-backup-v1", "bookverse-backup-v2"}:
            raise ValueError("This is not a supported BookVerse backup.")
        profile_payload = payload.get("profile") or {}
        if payload.get("format") == "bookverse-backup-v2" and profile_payload:
            current = self.get_profile(self._require_user_id()) or {}
            self.update_profile_preferences(
                profile_payload.get("display_name") or current.get("display_name") or "BookVerse User",
                profile_payload.get("favourite_niches") or current.get("favourite_niches") or [],
                profile_payload.get("top_books") or current.get("top_books") or [],
            )
        count = 0
        for item in payload.get("entries") or []:
            self.save_entry(
                Book.from_dict(item["book"]),
                shelf=item.get("shelf") or "Want to Read",
                user_rating=item.get("user_rating"),
                review=item.get("review") or "",
                progress_pages=int(item.get("progress_pages") or 0),
            )
            count += 1
        return count
