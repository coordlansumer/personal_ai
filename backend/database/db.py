"""PostgreSQL persistence for sessions and full message history."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("AI_DATABASE_URL", "postgresql://ai:ai@localhost:5432/ai")


async def _conn() -> AsyncConnection:
    return await AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)


async def init_db() -> None:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)"
            )


async def session_exists(session_id: str) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 FROM sessions WHERE id = %s", (session_id,))
            return await cur.fetchone() is not None


async def upsert_session(session_id: str) -> None:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO sessions (id, created_at, updated_at)
                VALUES (%s, now(), now())
                ON CONFLICT (id) DO UPDATE SET updated_at = now()
                """,
                (session_id,),
            )


async def list_sessions() -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            )
            rows = await cur.fetchall()
    return [
        {"id": r["id"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
        for r in rows
    ]


async def load_recent_messages(session_id: str, limit: int = 20) -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT role, content FROM messages
                WHERE session_id = %s
                ORDER BY id DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = await cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


async def append_messages(session_id: str, messages: list[dict]) -> None:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            for msg in messages:
                await cur.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                    (session_id, msg["role"], msg["content"]),
                )
