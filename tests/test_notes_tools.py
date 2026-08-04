from datetime import datetime, timezone

import pytest

from tools import notes as note_tools


async def test_create_note_stores_and_embeds(monkeypatch):
    embedded = []

    async def fake_create(content):
        return {"id": 3, "content": content, "created_at": "2026-08-04T10:00:00+00:00"}

    async def fake_store(note_id, content):
        embedded.append((note_id, content))

    monkeypatch.setattr("tools.notes.note_store.create_note", fake_create)
    monkeypatch.setattr("tools.notes.semantic.store_note", fake_store)
    result = await note_tools.create_note(content="买咖啡豆")
    assert result["id"] == 3
    assert embedded == [(3, "买咖啡豆")]


async def test_create_note_survives_embed_failure(monkeypatch):
    async def fake_create(content):
        return {"id": 3, "content": content}

    async def fake_store(note_id, content):
        raise RuntimeError("qdrant down")

    monkeypatch.setattr("tools.notes.note_store.create_note", fake_create)
    monkeypatch.setattr("tools.notes.semantic.store_note", fake_store)
    assert (await note_tools.create_note(content="x"))["id"] == 3


async def test_search_notes_returns_hits(monkeypatch):
    async def fake_search(query, top_k=5):
        return [{"note_id": "3", "content": "买咖啡豆", "score": 0.9}]

    monkeypatch.setattr("tools.notes.semantic.search_notes", fake_search)
    result = await note_tools.search_notes(query="咖啡")
    assert result["count"] == 1
    assert result["hits"][0]["content"] == "买咖啡豆"


async def test_delete_note_removes_both(monkeypatch):
    deleted = []

    async def fake_delete(note_id):
        return True

    async def fake_sem_delete(note_id):
        deleted.append(note_id)

    monkeypatch.setattr("tools.notes.note_store.delete_note", fake_delete)
    monkeypatch.setattr("tools.notes.semantic.delete_note", fake_sem_delete)
    assert await note_tools.delete_note(id=3) == {"deleted": True, "id": 3}
    assert deleted == [3]


async def test_create_note_serializes_datetime(monkeypatch):
    async def fake_create(content):
        return {"id": 3, "content": content, "created_at": datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)}

    monkeypatch.setattr("tools.notes.note_store.create_note", fake_create)
    result = await note_tools.create_note(content="买咖啡豆")
    assert result["created_at"] == "2026-08-04T10:00:00+00:00"


def test_tool_dicts_have_schemas():
    for t in [note_tools.create_note_tool, note_tools.search_notes_tool, note_tools.delete_note_tool]:
        assert t["name"]
        assert t["description"]
