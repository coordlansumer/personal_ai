"""PostgreSQL persistence for notes."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("AI_DATABASE_URL", "postgresql://ai:ai@localhost:5432/ai")


async def _conn() -> AsyncConnection:
    return await AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)


async def create_note(content: str) -> dict:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO notes (content) VALUES (%s) RETURNING id, content, created_at",
                (content,),
            )
            return await cur.fetchone()


async def get_note(note_id: int) -> dict | None:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, content, created_at FROM notes WHERE id = %s", (note_id,)
            )
            return await cur.fetchone()


async def delete_note(note_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0


async def list_notes(limit: int = 50) -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return await cur.fetchall()
