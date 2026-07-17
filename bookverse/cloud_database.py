from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import requests

from .database import LibraryDatabase


LOGGER = logging.getLogger(__name__)

_PATH_LOCKS: dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_RESTORED_PATHS: set[str] = set()
_CLOUD_ERRORS: dict[str, str] = {}


def _path_key(path: Path) -> str:
    return str(path.expanduser().resolve())


def _lock_for(path: Path) -> threading.RLock:
    key = _path_key(path)

    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)

        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock

        return lock


def _setting(name: str, default: str = "") -> str:
    value = os.getenv(name)

    if value is not None and str(value).strip():
        return str(value).strip()

    try:
        import streamlit as st

        value = st.secrets.get(name, default)

        if value is not None:
            return str(value).strip()
    except Exception:
        pass

    return default


class SupabaseSQLiteStorage:
    """Stores the BookVerse SQLite database in private Supabase Storage."""

    def __init__(self) -> None:
        self.project_url = _setting("SUPABASE_URL").rstrip("/")

        self.secret_key = (
            _setting("SUPABASE_SECRET_KEY")
            or _setting("SUPABASE_SERVICE_ROLE_KEY")
        )

        self.bucket = _setting(
            "SUPABASE_STORAGE_BUCKET",
            "bookverse-data",
        )

        self.object_name = _setting(
            "SUPABASE_DATABASE_FILE",
            "bookverse.db",
        )

        try:
            self.timeout = max(
                5,
                int(_setting("SUPABASE_STORAGE_TIMEOUT", "30")),
            )
        except ValueError:
            self.timeout = 30

    @property
    def enabled(self) -> bool:
        return bool(
            self.project_url
            and self.secret_key
            and self.bucket
            and self.object_name
        )

    @property
    def partly_configured(self) -> bool:
        return bool(self.project_url or self.secret_key) and not self.enabled

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
        }

    def _object_url(self, authenticated: bool) -> str:
        bucket = quote(self.bucket, safe="")
        object_name = quote(
            self.object_name.lstrip("/"),
            safe="/",
        )

        route = (
            "object/authenticated"
            if authenticated
            else "object"
        )

        return (
            f"{self.project_url}/storage/v1/"
            f"{route}/{bucket}/{object_name}"
        )

    def download_to(self, database_path: Path) -> bool:
        response = requests.get(
            self._object_url(authenticated=True),
            headers=self.headers,
            timeout=self.timeout,
        )

        if response.status_code == 404:
            return False

        if response.status_code != 200:
            raise RuntimeError(
                "Supabase database download failed with "
                f"HTTP {response.status_code}."
            )

        payload = response.content

        if not payload.startswith(b"SQLite format 3\x00"):
            raise RuntimeError(
                "The Supabase database object is not a valid SQLite file."
            )

        database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        handle, temporary_name = tempfile.mkstemp(
            prefix="bookverse-download-",
            suffix=".sqlite3",
            dir=str(database_path.parent),
        )

        os.close(handle)
        temporary_path = Path(temporary_name)

        try:
            temporary_path.write_bytes(payload)

            Path(f"{database_path}-wal").unlink(
                missing_ok=True
            )

            Path(f"{database_path}-shm").unlink(
                missing_ok=True
            )

            os.replace(
                temporary_path,
                database_path,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

        return True

    def upload_snapshot(
        self,
        database_path: Path,
    ) -> None:
        if not database_path.exists():
            return

        handle, temporary_name = tempfile.mkstemp(
            prefix="bookverse-upload-",
            suffix=".sqlite3",
            dir=str(database_path.parent),
        )

        os.close(handle)
        temporary_path = Path(temporary_name)

        source: sqlite3.Connection | None = None
        destination: sqlite3.Connection | None = None

        try:
            source = sqlite3.connect(
                database_path,
                timeout=20,
            )

            destination = sqlite3.connect(
                temporary_path,
                timeout=20,
            )

            source.backup(destination)
            destination.commit()
        finally:
            if destination is not None:
                destination.close()

            if source is not None:
                source.close()

        try:
            payload = temporary_path.read_bytes()

            if not payload.startswith(
                b"SQLite format 3\x00"
            ):
                raise RuntimeError(
                    "BookVerse could not create a valid SQLite snapshot."
                )

            headers = {
                **self.headers,
                "Content-Type": "application/octet-stream",
                "cache-control": "no-cache",
                "x-upsert": "true",
            }

            response = requests.post(
                self._object_url(
                    authenticated=False
                ),
                headers=headers,
                data=payload,
                timeout=self.timeout,
            )

            if response.status_code not in {
                200,
                201,
            }:
                raise RuntimeError(
                    "Supabase database upload failed with "
                    f"HTTP {response.status_code}."
                )
        finally:
            temporary_path.unlink(missing_ok=True)


class CloudLibraryDatabase(LibraryDatabase):
    """
    LibraryDatabase with automatic Supabase restore
    and backup.
    """

    def __init__(
        self,
        path: str | Path,
    ) -> None:
        self.path = Path(path)
        self._path_key = _path_key(self.path)
        self._path_lock = _lock_for(self.path)
        self._cloud = SupabaseSQLiteStorage()
        self._suppress_cloud_upload = 1

        with self._path_lock:
            first_instance = (
                self._path_key
                not in _RESTORED_PATHS
            )

            if first_instance:
                _RESTORED_PATHS.add(
                    self._path_key
                )

            remote_database_found = False

            if first_instance and self._cloud.enabled:
                try:
                    remote_database_found = (
                        self._cloud.download_to(
                            self.path
                        )
                    )

                    _CLOUD_ERRORS.pop(
                        self._path_key,
                        None,
                    )

                    if remote_database_found:
                        LOGGER.info(
                            "Restored BookVerse database "
                            "from Supabase."
                        )
                except Exception as exc:
                    self._record_cloud_error(exc)

            super().__init__(self.path)
            self._suppress_cloud_upload = 0

            if (
                first_instance
                and self._cloud.partly_configured
            ):
                self._record_cloud_error(
                    RuntimeError(
                        "Supabase settings are incomplete. "
                        "SUPABASE_URL and "
                        "SUPABASE_SECRET_KEY are required."
                    )
                )

            elif (
                first_instance
                and self._cloud.enabled
                and not remote_database_found
            ):
                self._upload_safely()

    @contextmanager
    def connection(
        self,
    ) -> Iterator[sqlite3.Connection]:
        with self._path_lock:
            changed = False

            with super().connection() as conn:
                changes_before = (
                    conn.total_changes
                )

                yield conn

                changed = (
                    conn.total_changes
                    > changes_before
                )

            if (
                changed
                and not self._suppress_cloud_upload
            ):
                self._upload_safely()

    def restore_payload(
        self,
        payload: dict,
    ) -> int:
        self._suppress_cloud_upload += 1

        try:
            count = super().restore_payload(
                payload
            )
        finally:
            self._suppress_cloud_upload -= 1

        self._upload_safely()
        return count

    @property
    def cloud_enabled(self) -> bool:
        return self._cloud.enabled

    @property
    def cloud_error(self) -> str:
        return _CLOUD_ERRORS.get(
            self._path_key,
            "",
        )

    def _record_cloud_error(
        self,
        exc: Exception,
    ) -> None:
        message = (
            str(exc)
            or exc.__class__.__name__
        )

        _CLOUD_ERRORS[self._path_key] = message

        LOGGER.error(
            "BookVerse Supabase persistence "
            "error: %s",
            message,
        )

    def _upload_safely(self) -> None:
        if not self._cloud.enabled:
            return

        try:
            self._cloud.upload_snapshot(
                self.path
            )

            _CLOUD_ERRORS.pop(
                self._path_key,
                None,
            )

            LOGGER.info(
                "Backed up BookVerse database "
                "to Supabase."
            )
        except Exception as exc:
            self._record_cloud_error(exc)
