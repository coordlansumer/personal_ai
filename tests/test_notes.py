import pytest

from database import notes


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

    monkeypatch.setattr(notes, "_conn", factory)
    return state


async def test_create_note_returns_row(fake_conn):
    fake_conn["conn"] = FakeConn(fetchone_row={"id": 3, "content": "买咖啡豆", "created_at": "2026-08-04T10:00:00+00:00"})
    row = await notes.create_note("买咖啡豆")
    assert row["id"] == 3
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "INSERT INTO notes" in sql
    assert params == ("买咖啡豆",)


async def test_get_note_returns_none_when_missing(fake_conn):
    fake_conn["conn"] = FakeConn(fetchone_row=None)
    assert await notes.get_note(99) is None


async def test_delete_note_returns_bool(fake_conn):
    assert await notes.delete_note(5) is True
    fake_conn["conn"].cursor_obj.rowcount = 0
    assert await notes.delete_note(5) is False


async def test_list_notes_returns_rows(fake_conn):
    fake_conn["conn"] = FakeConn(
        fetchall_results=[{"id": 1, "content": "买牛奶", "created_at": "2026-08-04T10:00:00+00:00"}]
    )
    rows = await notes.list_notes()
    assert rows[0]["content"] == "买牛奶"
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "ORDER BY id DESC" in sql
    assert params == (50,)
