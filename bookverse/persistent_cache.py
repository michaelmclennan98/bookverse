from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def _connect(database_path: str | Path) -> sqlite3.Connection:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS catalogue_cache (
            cache_key TEXT PRIMARY KEY,
            namespace TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            last_hit_at REAL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_catalogue_cache_expiry ON catalogue_cache(expires_at)"
    )
    conn.commit()
    return conn


def make_cache_key(namespace: str, *parts: Any) -> str:
    serialised = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(serialised.encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def get_cached(database_path: str | Path, namespace: str, *parts: Any) -> Any | None:
    if not database_path:
        return None
    key = make_cache_key(namespace, *parts)
    now = time.time()
    conn = _connect(database_path)
    try:
        row = conn.execute(
            "SELECT payload_json, expires_at FROM catalogue_cache WHERE cache_key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if float(row["expires_at"]) <= now:
            conn.execute("DELETE FROM catalogue_cache WHERE cache_key=?", (key,))
            conn.commit()
            return None
        conn.execute(
            """
            UPDATE catalogue_cache
            SET hit_count=hit_count+1, last_hit_at=?
            WHERE cache_key=?
            """,
            (now, key),
        )
        conn.commit()
        return json.loads(row["payload_json"])
    except (sqlite3.Error, json.JSONDecodeError, TypeError, ValueError):
        return None
    finally:
        conn.close()


def set_cached(
    database_path: str | Path,
    namespace: str,
    parts: tuple[Any, ...],
    payload: Any,
    ttl_seconds: int,
) -> None:
    if not database_path:
        return
    key = make_cache_key(namespace, *parts)
    now = time.time()
    conn = _connect(database_path)
    try:
        conn.execute(
            """
            INSERT INTO catalogue_cache(
                cache_key, namespace, payload_json, created_at, expires_at, hit_count, last_hit_at
            ) VALUES (?, ?, ?, ?, ?, 0, NULL)
            ON CONFLICT(cache_key) DO UPDATE SET
                namespace=excluded.namespace,
                payload_json=excluded.payload_json,
                created_at=excluded.created_at,
                expires_at=excluded.expires_at
            """,
            (
                key,
                namespace,
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
                now,
                now + max(60, int(ttl_seconds)),
            ),
        )
        conn.commit()
    except (sqlite3.Error, TypeError, ValueError):
        pass
    finally:
        conn.close()


def cache_stats(database_path: str | Path) -> dict[str, Any]:
    if not database_path:
        return {"entries": 0, "hits": 0, "expired": 0, "namespaces": {}}
    now = time.time()
    conn = _connect(database_path)
    try:
        rows = conn.execute(
            """
            SELECT namespace, COUNT(*) AS entries, SUM(hit_count) AS hits,
                   SUM(CASE WHEN expires_at <= ? THEN 1 ELSE 0 END) AS expired
            FROM catalogue_cache
            GROUP BY namespace
            ORDER BY namespace
            """,
            (now,),
        ).fetchall()
        namespaces = {
            str(row["namespace"]): {
                "entries": int(row["entries"] or 0),
                "hits": int(row["hits"] or 0),
                "expired": int(row["expired"] or 0),
            }
            for row in rows
        }
        return {
            "entries": sum(value["entries"] for value in namespaces.values()),
            "hits": sum(value["hits"] for value in namespaces.values()),
            "expired": sum(value["expired"] for value in namespaces.values()),
            "namespaces": namespaces,
        }
    finally:
        conn.close()


def prune_cache(database_path: str | Path, clear_all: bool = False) -> int:
    if not database_path:
        return 0
    conn = _connect(database_path)
    try:
        if clear_all:
            cursor = conn.execute("DELETE FROM catalogue_cache")
        else:
            cursor = conn.execute(
                "DELETE FROM catalogue_cache WHERE expires_at <= ?",
                (time.time(),),
            )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()
