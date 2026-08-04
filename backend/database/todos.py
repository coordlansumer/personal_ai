"""PostgreSQL persistence for todos."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("AI_DATABASE_URL", "postgresql://ai:ai@localhost:5432/ai")


async def _conn() -> AsyncConnection:
    return await AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)


async def create_todo(title: str, due_at: str | None = None, category: str | None = None) -> dict:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO todos (title, due_at, category)
                VALUES (%s, %s, %s)
                RETURNING id, title, status, category, due_at, created_at, completed_at
                """,
                (title, due_at, category),
            )
            return await cur.fetchone()


async def list_todos(status: str | None = None) -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            if status:
                await cur.execute(
                    "SELECT id, title, status, category, due_at, created_at, completed_at FROM todos WHERE status = %s ORDER BY id DESC",
                    (status,),
                )
            else:
                await cur.execute(
                    "SELECT id, title, status, category, due_at, created_at, completed_at FROM todos ORDER BY id DESC"
                )
            return await cur.fetchall()


async def complete_todo(todo_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE todos SET status = 'done', completed_at = now() WHERE id = %s AND status = 'pending'",
                (todo_id,),
            )
            return cur.rowcount > 0


async def delete_todo(todo_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM todos WHERE id = %s", (todo_id,))
            return cur.rowcount > 0
