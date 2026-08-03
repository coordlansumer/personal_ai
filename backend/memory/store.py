"""In-memory conversation store.

Keyed by session_id. Phase 1 keeps history in memory so the demo runs with
zero external services; Phase 2 replaces this class with a Redis/Qdrant
backing while keeping the same method signatures.
"""

from typing import Any
from uuid import uuid4


class MemoryStore:
    def __init__(self, max_history: int = 50) -> None:
        self._sessions: dict[str, list[dict[str, Any]]] = {}
        self._max_history = max_history

    def create_session(self) -> str:
        session_id = uuid4().hex
        self._sessions[session_id] = []
        return session_id

    def get_history(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._sessions.get(session_id, []))

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def add_message(self, session_id: str, role: str, content: str) -> None:
        messages = self._sessions.setdefault(session_id, [])
        messages.append({"role": role, "content": content})
        if len(messages) > self._max_history:
            del messages[: len(messages) - self._max_history]

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


store = MemoryStore()
