import pytest

from tools import todo as todo_tools


async def test_create_todo_calls_store(monkeypatch):
    captured = {}

    async def fake_create(title, due_at=None, category=None):
        captured.update(title=title, due_at=due_at, category=category)
        return {"id": 1, "title": title, "status": "pending"}

    monkeypatch.setattr("tools.todo.todo_store.create_todo", fake_create)
    result = await todo_tools.create_todo(title="买牛奶", due_at="2026-08-05T15:00:00")
    assert captured == {"title": "买牛奶", "due_at": "2026-08-05T15:00:00", "category": None}
    assert result["id"] == 1


async def test_list_todos_returns_wrapped(monkeypatch):
    async def fake_list(status=None):
        return [{"id": 1, "title": "开会", "status": "pending"}]

    monkeypatch.setattr("tools.todo.todo_store.list_todos", fake_list)
    result = await todo_tools.list_todos(status="pending")
    assert result["count"] == 1
    assert result["todos"][0]["title"] == "开会"


async def test_complete_todo(monkeypatch):
    async def fake_complete(todo_id):
        return True

    monkeypatch.setattr("tools.todo.todo_store.complete_todo", fake_complete)
    assert await todo_tools.complete_todo(id=7) == {"completed": True, "id": 7}


async def test_delete_todo(monkeypatch):
    async def fake_delete(todo_id):
        return True

    monkeypatch.setattr("tools.todo.todo_store.delete_todo", fake_delete)
    assert await todo_tools.delete_todo(id=7) == {"deleted": True, "id": 7}


def test_tool_dicts_have_schemas():
    for t in [todo_tools.create_todo_tool, todo_tools.list_todos_tool, todo_tools.complete_todo_tool, todo_tools.delete_todo_tool]:
        assert t["name"]
        assert t["description"]
        assert t["parameters"]["type"] == "object"
