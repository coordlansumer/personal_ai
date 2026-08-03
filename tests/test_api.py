import pytest
from fastapi.testclient import TestClient

from agent.chat_agent import APIKeyMissingError
from database import db
from main import app
from memory.store import MemoryStore
from api import routes


class FakeAgent:
    def validate_config(self):
        pass

    async def stream_chat(self, messages):
        for token in ["你", "好"]:
            yield token


class NoKeyAgent:
    def validate_config(self):
        raise APIKeyMissingError("未配置 DEEPSEEK_API_KEY")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "agent", FakeAgent())
    monkeypatch.setattr(routes, "store", MemoryStore())
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["llm_configured"] is True


def test_chat_streams_sse(client):
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text
    assert '"type": "session"' in body
    assert '"type": "token"' in body
    assert '"type": "done"' in body


def test_chat_saves_history_and_session(client):
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 200
    sessions = client.get("/api/sessions").json()["sessions"]
    assert len(sessions) == 1
    sid = sessions[0]["id"]
    history = routes.store.get_history(sid)
    assert history == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "你好"},
    ]


def test_chat_continues_existing_session(client):
    sid = routes.store.create_session()
    res = client.post("/api/chat", json={"message": "again", "session_id": sid})
    assert res.status_code == 200
    history = routes.store.get_history(sid)
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_chat_empty_message_returns_400(client):
    res = client.post("/api/chat", json={"message": "   "})
    assert res.status_code == 400


def test_chat_unknown_session_returns_404(client):
    res = client.post(
        "/api/chat", json={"message": "hi", "session_id": "deadbeef"}
    )
    assert res.status_code == 404


def test_chat_missing_api_key_returns_503(client, monkeypatch):
    monkeypatch.setattr(routes, "agent", NoKeyAgent())
    res = client.post("/api/chat", json={"message": "hi"})
    assert res.status_code == 503
    assert "DEEPSEEK_API_KEY" in res.json()["detail"]
