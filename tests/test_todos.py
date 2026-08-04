import pytest

from database import todos


class FakeCursor:
    def __init__(self, fetchall_results=None, fetchone_row=None):
        self.statements = []
        self._rows = fetchall_results or []
        self._row = fetchone_row
        self.rowcount = 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return self

    async def fetchone(self):
        return self._row

    async def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, **kw):
        self.cursor_obj = FakeCursor(**kw)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def cursor(self):
        return self.cursor_obj


@pytest.fixture
def fake_conn(monkeypatch):
    state = {"conn": FakeConn()}

    async def factory(**kw):
        return state["conn"]

    monkeypatch.setattr(todos, "_conn", factory)
    return state


async def test_create_todo_inserts_with_returning(fake_conn):
    fake_conn["conn"] = FakeConn(
        fetchone_row={"id": 1, "title": "买牛奶", "status": "pending", "category": None, "due_at": "2026-08-05T15:00:00+08:00", "created_at": "2026-08-04T10:00:00+00:00", "completed_at": None}
    )
    row = await todos.create_todo("买牛奶", due_at="2026-08-05T15:00:00+08:00", category="购物")
    assert row["id"] == 1
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "INSERT INTO todos" in sql
    assert "RETURNING" in sql
    assert params == ("买牛奶", "2026-08-05T15:00:00+08:00", "购物")


async def test_list_todos_filters_by_status(fake_conn):
    fake_conn["conn"] = FakeConn(fetchall_results=[{"id": 2, "title": "开会", "status": "done"}])
    rows = await todos.list_todos(status="done")
    assert rows == [{"id": 2, "title": "开会", "status": "done"}]
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "WHERE status = %s" in sql
    assert params == ("done",)


async def test_list_todos_all_when_no_status(fake_conn):
    fake_conn["conn"] = FakeConn(fetchall_results=[])
    await todos.list_todos()
    sql, _ = fake_conn["conn"].cursor_obj.statements[0]
    assert "WHERE" not in sql


async def test_complete_todo_updates_pending(fake_conn):
    ok = await todos.complete_todo(7)
    assert ok is True
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "status = 'done'" in sql
    assert "status = 'pending'" in sql
    assert params == (7,)


async def test_delete_todo_deletes(fake_conn):
    fake_conn["conn"].cursor_obj.rowcount = 0
    ok = await todos.delete_todo(7)
    assert ok is False
