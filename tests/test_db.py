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
        if not hasattr(factory, "_conn"):
            factory._conn = FakeConn(results)
        return factory._conn

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
