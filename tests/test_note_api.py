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


def test_list_notes_empty(client, monkeypatch):
    async def fake_list(limit=50):
        return []

    monkeypatch.setattr("api.routes.note_store.list_notes", fake_list)
    res = client.get("/api/notes")
    assert res.status_code == 200
    assert res.json() == {"notes": [], "count": 0}


def test_list_notes_returns_rows(client, monkeypatch):
    row = {"id": 2, "content": "买咖啡豆", "created_at": "2026-08-04T10:00:00+00:00"}

    async def fake_list(limit=50):
        return [row]

    monkeypatch.setattr("api.routes.note_store.list_notes", fake_list)
    res = client.get("/api/notes")
    assert res.status_code == 200
    assert res.json()["notes"][0]["content"] == "买咖啡豆"


def test_search_notes(client, monkeypatch):
    hits = [{"note_id": "2", "content": "明天下班买咖啡豆", "score": 0.87}]

    async def fake_search(query, top_k=5):
        return hits

    monkeypatch.setattr("api.routes.semantic.search_notes", fake_search)
    res = client.get("/api/notes/search", params={"q": "咖啡"})
    assert res.status_code == 200
    assert res.json() == {"hits": hits, "count": 1}


def test_search_notes_blank_q_400(client):
    res = client.get("/api/notes/search", params={"q": "   "})
    assert res.status_code == 400


def test_delete_note(client, monkeypatch):
    async def fake_delete(note_id):
        return True

    monkeypatch.setattr("api.routes.note_store.delete_note", fake_delete)
    res = client.delete("/api/notes/2")
    assert res.status_code == 200
    assert res.json() == {"deleted": True, "id": 2}


def test_delete_note_missing_404(client, monkeypatch):
    async def fake_delete(note_id):
        return False

    monkeypatch.setattr("api.routes.note_store.delete_note", fake_delete)
    res = client.delete("/api/notes/2")
    assert res.status_code == 404
