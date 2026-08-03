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


def test_chat_persistence_failure_still_yields_done(ctx, monkeypatch):
    async def _boom(sid, msgs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "append_messages", _boom)
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert '"type": "done"' in res.text


def test_chat_streams_when_upsert_fails(ctx, monkeypatch):
    async def _boom(sid):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "upsert_session", _boom)
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert '"type": "token"' in res.text
    assert '"type": "done"' in res.text


def test_chat_streams_when_session_exists_fails(ctx, monkeypatch):
    async def _boom(sid):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "session_exists", _boom)
    res = ctx["client"].post("/api/chat", json={"message": "hi", "session_id": "abc123"})
    assert res.status_code == 200
    assert '"type": "done"' in res.text


def test_recent_context_falls_back_to_db_when_redis_empty(ctx, monkeypatch):
    recent = [{"role": "assistant", "content": "早前回复"}]

    async def _load(sid, limit=20):
        return recent

    monkeypatch.setattr(db, "load_recent_messages", _load)
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert ctx["agent"].last_messages[0] == {"role": "assistant", "content": "早前回复"}
    assert len(ctx["short_term"].set_calls) >= 1


def test_recent_context_serves_db_when_redis_write_fails(ctx, monkeypatch):
    recent = [{"role": "assistant", "content": "早前回复"}]

    async def _load(sid, limit=20):
        return recent

    async def _boom(sid, messages):
        raise RuntimeError("redis down")

    monkeypatch.setattr(db, "load_recent_messages", _load)
    monkeypatch.setattr(short_term, "set_context", _boom)
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert ctx["agent"].last_messages[0] == {"role": "assistant", "content": "早前回复"}


def test_chat_with_empty_recall_injects_no_memory(ctx):
    res = ctx["client"].post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert ctx["agent"].last_memory_context is None


def test_startup_survives_qdrant_down(monkeypatch):
    async def _noop():
        pass

    async def _boom():
        raise RuntimeError("qdrant down")

    monkeypatch.setattr(db, "init_db", _noop)
    monkeypatch.setattr(semantic, "ensure_collection", _boom)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
