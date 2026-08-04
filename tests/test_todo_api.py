import pytest
from fastapi.testclient import TestClient

from database import db
from main import app
from memory.semantic import semantic


@pytest.fixture
def client(monkeypatch):
    async def _noop():
        pass

    monkeypatch.setattr(db, "init_db", _noop)
    monkeypatch.setattr(semantic, "ensure_collection", _noop)
    monkeypatch.setattr(semantic, "ensure_notes_collection", _noop)
    with TestClient(app) as c:
        yield c


def test_list_todos_empty(client, monkeypatch):
    async def fake_list(status=None):
        return []

    monkeypatch.setattr("api.routes.todo_store.list_todos", fake_list)
    res = client.get("/api/todos")
    assert res.status_code == 200
    assert res.json() == {"todos": [], "count": 0}


def test_list_todos_returns_rows(client, monkeypatch):
    row = {
        "id": 1,
        "title": "买牛奶",
        "status": "pending",
        "category": None,
        "due_at": "2026-08-05T15:00:00+08:00",
        "created_at": "2026-08-04T10:00:00+00:00",
        "completed_at": None,
    }

    async def fake_list(status=None):
        return [row]

    monkeypatch.setattr("api.routes.todo_store.list_todos", fake_list)
    res = client.get("/api/todos")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 1
    assert body["todos"][0]["title"] == "买牛奶"


def test_list_todos_passes_status(client, monkeypatch):
    captured = {}

    async def fake_list(status=None):
        captured["status"] = status
        return []

    monkeypatch.setattr("api.routes.todo_store.list_todos", fake_list)
    res = client.get("/api/todos", params={"status": "done"})
    assert res.status_code == 200
    assert captured["status"] == "done"


def test_create_todo(client, monkeypatch):
    async def fake_create(title, due_at=None, category=None):
        return {
            "id": 1,
            "title": title,
            "status": "pending",
            "category": category,
            "due_at": due_at,
            "created_at": "2026-08-04T10:00:00+00:00",
            "completed_at": None,
        }

    monkeypatch.setattr("api.routes.todo_store.create_todo", fake_create)
    res = client.post("/api/todos", json={"title": "买牛奶", "category": "购物"})
    assert res.status_code == 200
    assert res.json()["title"] == "买牛奶"
    assert res.json()["id"] == 1


def test_create_todo_blank_title_400(client):
    res = client.post("/api/todos", json={"title": "   "})
    assert res.status_code == 400
    assert res.json()["detail"] == "标题不能为空"


def test_complete_todo(client, monkeypatch):
    async def fake_complete(todo_id):
        return True

    monkeypatch.setattr("api.routes.todo_store.complete_todo", fake_complete)
    res = client.post("/api/todos/5/complete")
    assert res.status_code == 200
    assert res.json() == {"completed": True, "id": 5}


def test_complete_todo_missing_404(client, monkeypatch):
    async def fake_complete(todo_id):
        return False

    monkeypatch.setattr("api.routes.todo_store.complete_todo", fake_complete)
    res = client.post("/api/todos/5/complete")
    assert res.status_code == 404


def test_delete_todo(client, monkeypatch):
    async def fake_delete(todo_id):
        return True

    monkeypatch.setattr("api.routes.todo_store.delete_todo", fake_delete)
    res = client.delete("/api/todos/5")
    assert res.status_code == 200
    assert res.json() == {"deleted": True, "id": 5}


def test_delete_todo_missing_404(client, monkeypatch):
    async def fake_delete(todo_id):
        return False

    monkeypatch.setattr("api.routes.todo_store.delete_todo", fake_delete)
    res = client.delete("/api/todos/5")
    assert res.status_code == 404
