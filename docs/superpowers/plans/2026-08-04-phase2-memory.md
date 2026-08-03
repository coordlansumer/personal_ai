# Phase 2 长期记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Phase 1 聊天后端加三层长期记忆（PostgreSQL 全量持久化 + Redis 短期上下文 + Qdrant 语义检索），让 AI 跨会话、跨重启记住用户。

**Architecture:** 单一 FastAPI 容器不变，docker-compose 扩为 4 服务。写路径把每条消息同时落 Postgres、缓存进 Redis、向量化进 Qdrant；读路径先用 Redis 取近期上下文（未命中回源 Postgres），再用本地 embedding（fastembed + bge-small-zh-v1.5）检索 Qdrant top-k 相关记忆注入 system prompt。

**Tech Stack:** FastAPI, psycopg3 (async PostgreSQL), redis-py async, qdrant-client async, fastembed (ONNX, 本地 embedding), DeepSeek (OpenAI SDK)。

参考设计文档：`docs/superpowers/specs/2026-08-03-phase2-memory-design.md`

---

### 环境前置（本机特有）

- Docker Hub 被墙。构建前先经镜像源拉取并重打标签：
  ```bash
  docker pull docker.1ms.run/library/postgres:16-alpine && docker tag docker.1ms.run/library/postgres:16-alpine postgres:16-alpine
  docker pull docker.1ms.run/library/redis:7-alpine && docker tag docker.1ms.run/library/redis:7-alpine redis:7-alpine
  docker pull docker.1ms.run/qdrant/qdrant:v1.12.4 && docker tag docker.1ms.run/qdrant/qdrant:v1.12.4 qdrant/qdrant:v1.12.4
  ```
- 本地 venv 装依赖用清华源：`PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`

---

## Task 1: 添加 Phase 2 依赖

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 修改 requirements.txt**

将内容改为：

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
openai==1.59.6
python-dotenv==1.0.1
pydantic==2.10.4
psycopg[binary]==3.2.3
redis==5.2.1
qdrant-client==1.12.4
fastembed==0.4.1
```

- [ ] **Step 2: 安装到本地 venv**

Run:
```bash
cd "C:/Users/gry/program/personal_ai" && PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple .venv/Scripts/python -m pip install --quiet -r backend/requirements.txt -r requirements-dev.txt
```

- [ ] **Step 3: 验证可导入**

Run:
```bash
.venv/Scripts/python -c "import psycopg, redis, qdrant_client, fastembed; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt && git commit -m "chore: add Phase 2 memory dependencies"
```

---

## Task 2: 重写 database/db.py 为 PostgreSQL

**Files:**
- Rewrite: `backend/database/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_db.py`：

```python
import pytest

from database import db


class FakeCursor:
    def __init__(self, results=None):
        self.statements = []
        self._results = list(results or [])
        self._index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    async def fetchone(self):
        if self._index < len(self._results):
            row = self._results[self._index]
            self._index += 1
            return row
        return None

    async def fetchall(self):
        rows = self._results[self._index:]
        self._index = len(self._results)
        return rows


class FakeConn:
    def __init__(self, results=None):
        self.cursor_obj = FakeCursor(results)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def cursor(self):
        return self.cursor_obj


@pytest.fixture
def fake_db(monkeypatch):
    results = []

    async def factory():
        return FakeConn(results)

    monkeypatch.setattr(db, "_conn", factory)
    return results


async def test_init_db_creates_tables(fake_db):
    await db.init_db()
    conn = await db._conn()
    sql = " ".join(s for s, _ in conn.cursor_obj.statements)
    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS messages" in sql
    assert "idx_messages_session" in sql


async def test_session_exists_true(fake_db):
    fake_db.append({"id": "abc"})
    assert await db.session_exists("abc") is True


async def test_session_exists_false(fake_db):
    assert await db.session_exists("nope") is False


async def test_upsert_session_uses_on_conflict(fake_db):
    await db.upsert_session("abc")
    conn = await db._conn()
    sql = conn.cursor_obj.statements[0][0]
    assert "ON CONFLICT" in sql


async def test_list_sessions_returns_isoformat(fake_db):
    fake_db.append({"id": "s1", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-02T00:00:00+00:00"})
    rows = await db.list_sessions()
    assert rows[0]["id"] == "s1"
    assert rows[0]["created_at"] == "2026-01-01T00:00:00+00:00"


async def test_load_recent_messages_reverses_order(fake_db):
    fake_db.append({"role": "user", "content": "a"})
    fake_db.append({"role": "assistant", "content": "b"})
    rows = await db.load_recent_messages("s1", limit=5)
    assert rows == [
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "a"},
    ]


async def test_append_messages_inserts_each(fake_db):
    await db.append_messages("s1", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}])
    conn = await db._conn()
    assert len(conn.cursor_obj.statements) == 2
    assert conn.cursor_obj.statements[0][1] == ("s1", "user", "hi")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -q`
Expected: 失败（模块里没有这些函数 / 旧 SQLite 行为不符）

- [ ] **Step 3: 重写实现** — 覆盖 `backend/database/db.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/database/db.py tests/test_db.py && git commit -m "feat: replace SQLite with PostgreSQL persistence"
```

---

## Task 3: 新增 memory/short_term.py（Redis 短期上下文）

**Files:**
- Create: `backend/memory/short_term.py`
- Create: `tests/test_short_term.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_short_term.py`：

```python
import pytest

from memory.short_term import ShortTermMemory


class FakeRedis:
    def __init__(self):
        self.data = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        self.data[key] = value

    async def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture
def mem():
    return ShortTermMemory(redis_client=FakeRedis(), context_limit=3)


async def test_get_context_unknown_returns_none(mem):
    assert await mem.get_context("nope") is None


async def test_set_then_get_roundtrip(mem):
    msgs = [{"role": "user", "content": "hi"}]
    await mem.set_context("s1", msgs)
    assert await mem.get_context("s1") == msgs


async def test_set_context_truncates_to_limit(mem):
    msgs = [{"role": "user", "content": str(i)} for i in range(5)]
    await mem.set_context("s1", msgs)
    assert len(await mem.get_context("s1")) == 3


async def test_delete_removes(mem):
    await mem.set_context("s1", [{"role": "user", "content": "hi"}])
    await mem.delete_context("s1")
    assert await mem.get_context("s1") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_short_term.py -q`
Expected: 失败（模块不存在）

- [ ] **Step 3: 实现** — 创建 `backend/memory/short_term.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_short_term.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/memory/short_term.py tests/test_short_term.py && git commit -m "feat: add Redis short-term context memory"
```

---

## Task 4: 新增 memory/semantic.py（Qdrant 语义记忆）

**Files:**
- Create: `backend/memory/semantic.py`
- Create: `tests/test_semantic.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_semantic.py`：

```python
from types import SimpleNamespace

import pytest

from memory.semantic import COLLECTION, SemanticMemory


class FakeEmbedder:
    def __init__(self, dim=4):
        self.dim = dim
        self.called_with = []

    def embed(self, texts):
        self.called_with.extend(texts)
        for _ in texts:
            yield [0.1] * self.dim


class FakeHit:
    def __init__(self, score, payload):
        self.score = score
        self.payload = payload


class FakeQdrant:
    def __init__(self, collection_names=None):
        self.names = set(collection_names or [])
        self.created = []
        self.upserted = []
        self.hits = []
        self.last_search = {}

    async def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.names])

    async def create_collection(self, name, vectors_config):
        self.created.append((name, vectors_config))

    async def upsert(self, collection, points):
        self.upserted.extend(points)

    async def search(self, collection, query_vector, limit, with_payload):
        self.last_search = {"collection": collection, "limit": limit}
        return self.hits


@pytest.fixture
def mem():
    fake = FakeQdrant()
    sm = SemanticMemory(embedder=FakeEmbedder(), client=fake)
    sm._qdrant = fake
    return sm


async def test_ensure_collection_creates_when_missing(mem):
    await mem.ensure_collection()
    assert mem._qdrant.created[0][0] == COLLECTION


async def test_ensure_collection_skips_when_exists():
    fake = FakeQdrant(collection_names=[COLLECTION])
    sm = SemanticMemory(embedder=FakeEmbedder(), client=fake)
    await sm.ensure_collection()
    assert fake.created == []


async def test_store_message_embeds_and_upserts(mem):
    await mem.store_message("s1", "user", "我喜欢咖啡")
    point = mem._qdrant.upserted[0]
    assert point.payload["session_id"] == "s1"
    assert point.payload["role"] == "user"
    assert point.payload["content"] == "我喜欢咖啡"
    assert len(point.vector) == 4


async def test_recall_filters_below_threshold(mem):
    mem._qdrant.hits = [
        FakeHit(score=0.9, payload={"content": "A", "role": "user", "created_at": "2026-01-01T00:00:00+00:00"}),
        FakeHit(score=0.1, payload={"content": "B", "role": "assistant", "created_at": "2026-01-01T00:00:00+00:00"}),
    ]
    results = await mem.recall("咖啡")
    assert [r["content"] for r in results] == ["A"]
    assert results[0]["score"] == 0.9
    assert mem._qdrant.last_search["limit"] == 5
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_semantic.py -q`
Expected: 失败（模块不存在）

- [ ] **Step 3: 实现** — 创建 `backend/memory/semantic.py`：

```python
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
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_semantic.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/memory/semantic.py tests/test_semantic.py && git commit -m "feat: add Qdrant semantic memory with local embeddings"
```

---

## Task 5: chat_agent 支持 memory_context

**Files:**
- Modify: `backend/agent/chat_agent.py:57-75`
- Test: `tests/test_chat_agent.py`

- [ ] **Step 1: 写失败测试** — 在 `tests/test_chat_agent.py` 末尾追加：

```python
async def test_stream_chat_injects_memory_context(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    tokens = []
    async for t in agent.stream_chat(
        [{"role": "user", "content": "hi"}],
        memory_context="以下是检索到的历史记忆：\n- 用户说：我喜欢咖啡",
    ):
        tokens.append(t)
    assert tokens == ["你", "好"]

    captured = agent._get_client().chat.completions.captured
    system = captured["messages"][0]["content"]
    assert "以下是检索到的历史记忆" in system
    assert "我喜欢咖啡" in system
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_chat_agent.py::test_stream_chat_injects_memory_context -q`
Expected: 失败（TypeError: stream_chat() got an unexpected keyword argument 'memory_context'）

- [ ] **Step 3: 修改实现** — 在 `backend/agent/chat_agent.py` 把 `stream_chat` 改为：

```python
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        memory_context: str | None = None,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        system = SYSTEM_PROMPT
        if memory_context:
            system = f"{system}\n\n{memory_context}"
        full_messages = [{"role": "system", "content": system}, *messages]
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                stream=True,
                temperature=0.7,
            )
        except Exception as exc:  # network / auth errors from the provider
            raise LLMError(f"调用 DeepSeek 失败: {exc}") from exc

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_chat_agent.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agent/chat_agent.py tests/test_chat_agent.py && git commit -m "feat: inject recalled memory into system prompt"
```

---

## Task 6: 重写 api/routes.py 接入三层记忆

**Files:**
- Rewrite: `backend/api/routes.py`
- Rewrite: `tests/test_api.py`

- [ ] **Step 1: 重写测试** — 覆盖 `tests/test_api.py`：

```python
import pytest
from fastapi.testclient import TestClient

from agent.chat_agent import APIKeyMissingError
from database import db
from main import app
from memory.semantic import semantic
from memory.short_term import short_term


class FakeAgent:
    def __init__(self):
        self.last_messages = None
        self.last_memory_context = None

    def validate_config(self):
        pass

    async def stream_chat(self, messages, memory_context=None):
        self.last_messages = messages
        self.last_memory_context = memory_context
        for token in ["你", "好"]:
            yield token


class NoKeyAgent:
    def validate_config(self):
        raise APIKeyMissingError("未配置 DEEPSEEK_API_KEY")


class FakeDB:
    def __init__(self):
        self.session_ids = set()
        self.appended = []
        self.sessions_list = []

    async def session_exists(self, sid):
        return sid in self.session_ids

    async def upsert_session(self, sid):
        self.session_ids.add(sid)

    async def list_sessions(self):
        return self.sessions_list

    async def load_recent_messages(self, sid, limit=20):
        return []

    async def append_messages(self, sid, msgs):
        self.appended.append((sid, msgs))


class FakeSemantic:
    def __init__(self):
        self.recall_results = []
        self.recall_error = None
        self.stored = []

    async def recall(self, message):
        if self.recall_error:
            raise self.recall_error
        return self.recall_results

    async def store_message(self, sid, role, content):
        self.stored.append((sid, role, content))


class FakeShortTerm:
    def __init__(self):
        self.contexts = {}
        self.set_calls = []

    async def get_context(self, sid):
        return self.contexts.get(sid)

    async def set_context(self, sid, messages):
        self.contexts[sid] = messages
        self.set_calls.append((sid, messages))


@pytest.fixture
def ctx(monkeypatch):
    async def _noop():
        pass

    fake_db = FakeDB()
    fake_semantic = FakeSemantic()
    fake_short = FakeShortTerm()
    fake_agent = FakeAgent()

    monkeypatch.setattr(db, "init_db", _noop)
    monkeypatch.setattr(db, "session_exists", fake_db.session_exists)
    monkeypatch.setattr(db, "upsert_session", fake_db.upsert_session)
    monkeypatch.setattr(db, "list_sessions", fake_db.list_sessions)
    monkeypatch.setattr(db, "load_recent_messages", fake_db.load_recent_messages)
    monkeypatch.setattr(db, "append_messages", fake_db.append_messages)
    monkeypatch.setattr(semantic, "ensure_collection", _noop)
    monkeypatch.setattr(semantic, "recall", fake_semantic.recall)
    monkeypatch.setattr(semantic, "store_message", fake_semantic.store_message)
    monkeypatch.setattr(short_term, "get_context", fake_short.get_context)
    monkeypatch.setattr(short_term, "set_context", fake_short.set_context)
    monkeypatch.setattr("api.routes.agent", fake_agent)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    with TestClient(app) as client:
        yield {"client": client, "db": fake_db, "semantic": fake_semantic, "short_term": fake_short, "agent": fake_agent}


def test_health(ctx):
    res = ctx["client"].get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["llm_configured"] is True


def test_chat_streams_sse(ctx):
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text
    assert '"type": "session"' in body
    assert '"type": "token"' in body
    assert '"type": "done"' in body


def test_chat_persists_to_all_layers(ctx):
    ctx["client"].post("/api/chat", json={"message": "hi"})
    assert len(ctx["db"].appended) == 1
    sid, msgs = ctx["db"].appended[0]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert ctx["short_term"].contexts[sid] == msgs
    assert [(r, c) for _, r, c in ctx["semantic"].stored] == [("user", "hi"), ("assistant", "你好")]


def test_chat_injects_memory_block(ctx):
    ctx["semantic"].recall_results = [
        {"content": "我喜欢咖啡", "role": "user", "created_at": "2026-01-01T00:00:00+00:00", "score": 0.9}
    ]
    res = ctx["client"].post("/api/chat", json={"message": "咖啡"})
    assert res.status_code == 200
    assert ctx["agent"].last_memory_context is not None
    assert "我喜欢咖啡" in ctx["agent"].last_memory_context


def test_chat_degrades_when_recall_fails(ctx):
    ctx["semantic"].recall_error = RuntimeError("qdrant down")
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert ctx["agent"].last_memory_context is None


def test_chat_empty_message_returns_400(ctx):
    res = ctx["client"].post("/api/chat", json={"message": "   "})
    assert res.status_code == 400


def test_chat_unknown_session_returns_404(ctx):
    res = ctx["client"].post("/api/chat", json={"message": "hi", "session_id": "deadbeef"})
    assert res.status_code == 404


def test_chat_missing_api_key_returns_503(ctx, monkeypatch):
    monkeypatch.setattr("api.routes.agent", NoKeyAgent())
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 503
    assert "DEEPSEEK_API_KEY" in res.json()["detail"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -q`
Expected: 失败（routes 还是旧实现，引用已删除的 memory.store）

- [ ] **Step 3: 重写实现** — 覆盖 `backend/api/routes.py`：

```python
"""HTTP routes for the Personal AI OS backend."""

import json
import logging
import os
from typing import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.chat_agent import APIKeyMissingError, LLMError, agent
from database import db
from memory.semantic import semantic
from memory.short_term import short_term

logger = logging.getLogger("personal_ai.api")

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _sse(event_type: str, payload: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


def _build_memory_block(hits: list[dict]) -> str:
    lines = "\n".join(
        f"- [{hit['created_at'][:10]}] {hit['role']}：{hit['content']}" for hit in hits
    )
    return (
        "以下是检索到的历史记忆：\n"
        + lines
        + "\n请结合这些记忆回答，但不要编造记忆里没有的内容。"
    )


@router.get("/health")
async def health() -> dict:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    return {
        "status": "ok",
        "llm_configured": bool(api_key),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    }


@router.get("/sessions")
async def sessions() -> dict:
    return {"sessions": await db.list_sessions()}


async def _recent_context(session_id: str) -> list[dict]:
    try:
        cached = await short_term.get_context(session_id)
        if cached is not None:
            return cached
    except Exception as exc:
        logger.warning("Redis read failed, falling back to DB: %s", exc)
    try:
        recent = await db.load_recent_messages(session_id)
        await short_term.set_context(session_id, recent)
        return recent
    except Exception as exc:
        logger.warning("DB context load failed: %s", exc)
        return []


async def _recall_memory(message: str) -> str | None:
    try:
        hits = await semantic.recall(message)
    except Exception as exc:
        logger.warning("Semantic recall failed, proceeding without memory: %s", exc)
        return None
    return _build_memory_block(hits) if hits else None


@router.post("/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    if req.session_id:
        session_id = req.session_id
        try:
            if not await db.session_exists(session_id):
                raise HTTPException(status_code=404, detail="会话不存在")
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("session_exists failed, continuing: %s", exc)
    else:
        session_id = uuid4().hex

    await db.upsert_session(session_id)
    recent = await _recent_context(session_id)
    history = [*recent, {"role": "user", "content": message}]
    memory_block = await _recall_memory(message)

    # Fail fast with a clean HTTP status if the API key is missing.
    try:
        agent.validate_config()
    except APIKeyMissingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": session_id})
        parts: list[str] = []
        try:
            async for token in agent.stream_chat(history, memory_context=memory_block):
                parts.append(token)
                yield _sse("token", {"content": token})
        except LLMError as exc:
            logger.error("LLM streaming failed for session %s: %s", session_id, exc)
            yield _sse("error", {"message": str(exc)})
            return
        except Exception as exc:
            logger.exception("Unhandled streaming error for session %s", session_id)
            yield _sse("error", {"message": f"服务内部错误: {exc}"})
            return

        # Persistence is best-effort and must not fail the stream.
        try:
            reply = "".join(parts)
            new_messages = [
                {"role": "user", "content": message},
                {"role": "assistant", "content": reply},
            ]
            await db.append_messages(session_id, new_messages)
            await db.upsert_session(session_id)
            await short_term.set_context(session_id, [*recent, *new_messages])
            await semantic.store_message(session_id, "user", message)
            await semantic.store_message(session_id, "assistant", reply)
        except Exception as exc:
            logger.warning("Persistence failed for session %s: %s", session_id, exc)
        yield _sse("done", {})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/routes.py tests/test_api.py && git commit -m "feat: wire three-layer memory into chat endpoint"
```

---

## Task 7: main.py 初始化 + 删除旧内存 store

**Files:**
- Modify: `backend/main.py`
- Delete: `backend/memory/store.py`, `tests/test_memory.py`

- [ ] **Step 1: 修改 main.py** — 覆盖为：

```python
"""Personal AI OS backend entrypoint."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router
from database import db
from memory.semantic import semantic

logger = logging.getLogger("personal_ai")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await db.init_db()
    try:
        await semantic.ensure_collection()
    except Exception as exc:
        logger.warning("Qdrant unavailable at startup: %s", exc)
    yield


app = FastAPI(title="Personal AI OS", version="0.2.0", lifespan=lifespan)
app.include_router(router)

STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 2: 删除旧内存 store 及其测试**

```bash
git rm backend/memory/store.py tests/test_memory.py
```

- [ ] **Step 3: 跑全量测试**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 全部 PASS（不再有引用 store.py 的代码）

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor: initialize Phase 2 memory, remove in-memory store"
```

---

## Task 8: Docker Compose + env + Dockerfile 模型烘焙

**Files:**
- Rewrite: `docker-compose.yml`
- Modify: `.env`, `.env.example`, `Dockerfile`

- [ ] **Step 1: 重写 docker-compose.yml**：

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: ai
      POSTGRES_PASSWORD: ai
      POSTGRES_DB: ai
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ai -d ai"]
      interval: 5s
      timeout: 3s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10

  qdrant:
    image: qdrant/qdrant:v1.12.4
    ports:
      - "6333:6333"
    volumes:
      - qdrantdata:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/readyz"]
      interval: 5s
      timeout: 3s
      retries: 10

  ai-backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: personal-ai-backend
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      AI_DATABASE_URL: postgresql://ai:ai@postgres:5432/ai
      REDIS_URL: redis://redis:6379/0
      QDRANT_URL: http://qdrant:6333
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
  qdrantdata:
```

- [ ] **Step 2: 更新 .env 和 .env.example** — 在两者末尾追加（`.env` 保持真实 key，`.env.example` 保持空 key）：

```
# Phase 2 memory services（docker-compose 内用容器名，本地开发用 localhost）
AI_DATABASE_URL=postgresql://ai:ai@localhost:5432/ai
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
MEMORY_TOP_K=5
MEMORY_THRESHOLD=0.35
MEMORY_CONTEXT_LIMIT=20
```

- [ ] **Step 3: 更新 Dockerfile** — 覆盖为：

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_ENDPOINT=https://hf-mirror.com

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m -u 1000 appuser

COPY backend/ ./backend/

ENV FASTEMBED_CACHE_DIR=/app/fastembed-cache
RUN mkdir -p "$FASTEMBED_CACHE_DIR" && chown -R appuser:appuser /app

USER appuser
# Bake the embedding model into the image so runtime never hits the network.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5', cache_dir='/app/fastembed-cache')"

WORKDIR /app/backend

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 4: 拉取新基础镜像（走镜像源）**

```bash
docker pull docker.1ms.run/library/postgres:16-alpine && docker tag docker.1ms.run/library/postgres:16-alpine postgres:16-alpine
docker pull docker.1ms.run/library/redis:7-alpine && docker tag docker.1ms.run/library/redis:7-alpine redis:7-alpine
docker pull docker.1ms.run/qdrant/qdrant:v1.12.4 && docker tag docker.1ms.run/qdrant/qdrant:v1.12.4 qdrant/qdrant:v1.12.4
```

- [ ] **Step 5: 停旧容器并重建**

```bash
docker compose down && docker compose build 2>&1 | tail -20
```
Expected: 构建成功（模型下载走 hf-mirror，pip 走清华源）

- [ ] **Step 6: 启动全部服务**

```bash
docker compose up -d
```
Expected: 4 个容器 healthy 后 ai-backend 启动

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: compose stack with postgres/redis/qdrant, bake embedding model"
```

---

## Task 9: 集成验证

**Files:** 无（验证性任务）

- [ ] **Step 1: 健康检查**

```bash
curl -s http://localhost:8000/api/health
```
Expected: `{"status":"ok","llm_configured":true,"model":"deepseek-chat"}`

- [ ] **Step 2: 建立记忆事实**（用文件避免 Windows 编码问题）

```bash
printf '{"message":"记住，我最喜欢的咖啡是美式"}' > /tmp/m1.json
curl -s -m 60 -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" --data @/tmp/m1.json | grep -c '"type": "done"'
```
Expected: 输出 `1`，且没有 `"type": "error"`

- [ ] **Step 3: 验证容器重启后不丢失（Postgres + Redis 持久化）**

```bash
docker compose restart ai-backend
curl -s -m 60 -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" --data '{"message":"我刚才说了什么咖啡？","session_id":"<第一步返回的session_id>"}'
```
Expected: 能复述"美式咖啡"（同一 session 上下文经 Postgres 回源恢复）

- [ ] **Step 4: 验证跨会话语义记忆（Qdrant）**

```bash
printf '{"message":"你知道我喜欢喝什么咖啡吗？"}' > /tmp/m2.json
curl -s -m 60 -X POST http://localhost:8000/api/chat -H "Content-Type: application/json" --data @/tmp/m2.json
```
Expected: 不携带 session_id（新会话），仍能答出"美式"——证明向量检索跨会话生效

- [ ] **Step 5: 浏览器冒烟** — 打开 http://localhost:8000，发一条消息确认 UI 正常

- [ ] **Step 6: 清理临时文件并做最终提交**

```bash
rm -f /tmp/m1.json /tmp/m2.json
git status --short
```

---

## Self-Review 记录

- **Spec 覆盖**：三层（Redis/Qdrant/Postgres）✓；整段对话向量化写入+检索 ✓；本地 embedding ✓；降级路径 ✓；重启不丢 ✓；跨会话记忆 ✓。
- **类型一致性**：`db.*`、`short_term.*`、`semantic.*` 方法签名在各任务间一致（routes 调用与模块实现匹配）；`stream_chat(messages, memory_context=None)` 在 Task 5 定义、Task 6 使用。
- **占位符扫描**：无 TBD/TODO，每步含完整代码与命令。
