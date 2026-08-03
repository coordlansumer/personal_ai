"""Qdrant-backed long-term semantic memory.

Each message is embedded locally (fastembed + BAAI/bge-small-zh-v1.5) and
stored as a vector point. On each turn the current user message is embedded
and the top-k similar past messages are recalled across all sessions.
"""

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
COLLECTION = "conversation_memories"
VECTOR_SIZE = 512

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")


class SemanticMemory:
    def __init__(self, embedder=None, client=None) -> None:
        self._embedder = embedder
        self._client = client
        self.collection = COLLECTION

    def _get_embedder(self) -> TextEmbedding:
        if self._embedder is None:
            self._embedder = TextEmbedding(
                MODEL_NAME,
                cache_dir=os.getenv("FASTEMBED_CACHE_DIR") or None,
            )
        return self._embedder

    def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            self._client = AsyncQdrantClient(url=QDRANT_URL)
        return self._client

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._get_embedder().embed(texts)]

    async def ensure_collection(self) -> None:
        client = self._get_client()
        collections = await client.get_collections()
        names = {c.name for c in collections.collections}
        if self.collection not in names:
            await client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    async def store_message(self, session_id: str, role: str, content: str) -> None:
        vector = self._embed([content])[0]
        point = PointStruct(
            id=uuid4().hex,
            vector=vector,
            payload={
                "session_id": session_id,
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._get_client().upsert(self.collection, points=[point])

    async def recall(self, query_text: str) -> list[dict[str, Any]]:
        top_k = int(os.getenv("MEMORY_TOP_K", "5"))
        threshold = float(os.getenv("MEMORY_THRESHOLD", "0.35"))
        vector = self._embed([query_text])[0]
        hits = await self._get_client().search(
            self.collection, query_vector=vector, limit=top_k, with_payload=True
        )
        results = []
        for hit in hits:
            if hit.score >= threshold:
                payload = hit.payload
                results.append(
                    {
                        "content": payload.get("content", ""),
                        "role": payload.get("role", ""),
                        "created_at": payload.get("created_at", ""),
                        "score": round(hit.score, 4),
                    }
                )
        return results


semantic = SemanticMemory()
