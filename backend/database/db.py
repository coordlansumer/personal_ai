"""SQLite persistence for session metadata.

Phase 1 keeps this deliberately thin: it only stores session rows.
Phase 2 swaps the underlying engine for PostgreSQL without touching callers.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.getenv("AI_DB_PATH", os.path.join(os.path.dirname(__file__), "ai.db"))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def upsert_session(session_id: str) -> None:
    now = utcnow()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (session_id, now, now),
        )


def list_sessions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {"id": r[0], "created_at": r[1], "updated_at": r[2]} for r in rows
    ]
