"""Redis-backed short-term memory: the recent context window per session."""

import json
import os
from typing import Any

import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _key(session_id: str) -> str:
    return f"session:{session_id}:context"


class ShortTermMemory:
    def __init__(self, redis_client=None, context_limit: int | None = None) -> None:
        self._client = redis_client
        self.context_limit = context_limit or int(os.getenv("MEMORY_CONTEXT_LIMIT", "20"))

    def _get_client(self):
        if self._client is None:
            self._client = redis.from_url(REDIS_URL, decode_responses=True)
        return self._client

    async def get_context(self, session_id: str) -> list[dict[str, Any]] | None:
        raw = await self._get_client().get(_key(session_id))
        return json.loads(raw) if raw else None

    async def set_context(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        await self._get_client().set(
            _key(session_id),
            json.dumps(messages[-self.context_limit :], ensure_ascii=False),
        )

    async def delete_context(self, session_id: str) -> None:
        await self._get_client().delete(_key(session_id))


short_term = ShortTermMemory()
