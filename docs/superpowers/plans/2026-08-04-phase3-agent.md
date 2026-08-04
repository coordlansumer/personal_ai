# Phase 3 Agent 工具调用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Personal AI OS 加响应式工具调用能力——新增 9 个内置工具（now/calculate/待办 CRUD×4/备忘 CRUD×3），让 `/api/chat` 从纯聊天升级为「规划→调用→执行→回复」闭环，并迁移 DeepSeek 模型名。

**Architecture:** 独立 `tools/` 包（注册表 + 工具定义）+ `agent/orchestrator.py`（响应式循环 ≤5 轮）。`ChatAgent.stream_chat` 改为产出事件 dict（content / tool_call_delta），orchestrator 从中累积 tool_calls、执行工具、把结果以 `role:"tool"` 喂回 LLM。SSE 新增 `tool` 事件，前端渲染工具卡片 + 记笔记按钮。

**Tech Stack:** Python 3.12 / FastAPI / OpenAI SDK / psycopg3 / qdrant-client / fastembed。零新增依赖。

**Spec:** `docs/superpowers/specs/2026-08-04-phase3-agent-design.md`

## Global Constraints

- LLM 走 DeepSeek，`DEFAULT_MODEL = "deepseek-v4-flash"`（旧名 `deepseek-chat` 已退役），保留 `DEEPSEEK_MODEL` env 覆盖
- 不用 eval/exec：`calculate` 用 ast 白名单 + 递归求值器
- 工具调用/结果不写入 messages 表——只落库最终 user + assistant 文本；todos/notes 表是持久记录
- `note_memories` 是独立 Qdrant 集合，与 `conversation_memories` 隔离，`semantic.recall` 只搜会话记忆
- 工具执行失败必须转 error 结果回给 LLM，绝不中断循环
- 测试不依赖真实服务（mock `_conn`/embedder/Qdrant client/fake LLM），沿用现有 fake + monkeypatch 风格
- 代码与文档用中文注释/描述，UI 文案中文，不用 emoji

---

### Task 1: 数据库存储层 todos + notes

**Files:**
- Modify: `backend/database/db.py`（`init_db` 增加两张表）
- Create: `backend/database/todos.py`
- Create: `backend/database/notes.py`
- Modify: `tests/test_db.py`（扩展 init_db 断言）
- Create: `tests/test_todos.py`, `tests/test_notes.py`

**Interfaces:**
- Produces:
  - `database.todos`: `async create_todo(title: str, due_at: str|None, category: str|None) -> dict`；`async list_todos(status: str|None) -> list[dict]`；`async complete_todo(todo_id: int) -> bool`；`async delete_todo(todo_id: int) -> bool`
  - `database.notes`: `async create_note(content: str) -> dict`；`async get_note(note_id: int) -> dict|None`；`async delete_note(note_id: int) -> bool`
  - 每个模块自带 `_conn()`（与 db.py 同款），供测试 monkeypatch

- [ ] **Step 1: 写 init_db 扩展测试（先失败）**

在 `tests/test_db.py` 的 `test_init_db_creates_tables` 里追加断言：

```python
async def test_init_db_creates_tables(fake_db):
    await db.init_db()
    conn = await db._conn()
    sql = " ".join(s for s, _ in conn.cursor_obj.statements)
    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS messages" in sql
    assert "CREATE TABLE IF NOT EXISTS todos" in sql
    assert "CREATE TABLE IF NOT EXISTS notes" in sql
    assert "idx_messages_session" in sql
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_db.py::test_init_db_creates_tables -v`
Expected: FAIL（`assert "CREATE TABLE IF NOT EXISTS todos" in sql` 失败）

- [ ] **Step 3: 在 db.py 的 init_db 增加建表**

```python
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS todos (
                    id BIGSERIAL PRIMARY KEY,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    category TEXT,
                    due_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id BIGSERIAL PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
```

（插入到 `idx_messages_session` 那条 `CREATE INDEX` 之前即可。）

- [ ] **Step 4: 写 todos 存储测试（先失败）**

创建 `tests/test_todos.py`：

```python
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
    state = {}

    async def factory(**kw):
        conn = FakeConn(**kw)
        state["conn"] = conn
        return conn

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
```

- [ ] **Step 5: 运行确认失败**

Run: `pytest tests/test_todos.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'database.todos'`）

- [ ] **Step 6: 实现 database/todos.py**

```python
"""PostgreSQL persistence for todos."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("AI_DATABASE_URL", "postgresql://ai:ai@localhost:5432/ai")


async def _conn() -> AsyncConnection:
    return await AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)


async def create_todo(title: str, due_at: str | None = None, category: str | None = None) -> dict:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO todos (title, due_at, category)
                VALUES (%s, %s, %s)
                RETURNING id, title, status, category, due_at, created_at, completed_at
                """,
                (title, due_at, category),
            )
            return await cur.fetchone()


async def list_todos(status: str | None = None) -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            if status:
                await cur.execute(
                    "SELECT id, title, status, category, due_at, created_at, completed_at FROM todos WHERE status = %s ORDER BY id DESC",
                    (status,),
                )
            else:
                await cur.execute(
                    "SELECT id, title, status, category, due_at, created_at, completed_at FROM todos ORDER BY id DESC"
                )
            return await cur.fetchall()


async def complete_todo(todo_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE todos SET status = 'done', completed_at = now() WHERE id = %s AND status = 'pending'",
                (todo_id,),
            )
            return cur.rowcount > 0


async def delete_todo(todo_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM todos WHERE id = %s", (todo_id,))
            return cur.rowcount > 0
```

- [ ] **Step 7: 运行确认通过**

Run: `pytest tests/test_db.py tests/test_todos.py -v`
Expected: PASS

- [ ] **Step 8: 写 notes 存储测试（先失败）**

创建 `tests/test_notes.py`（复用上文的 FakeCursor/FakeConn/fake_conn 结构，此处仅列用例差异）：

```python
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
```

- [ ] **Step 9: 运行确认失败**

Run: `pytest tests/test_notes.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 10: 实现 database/notes.py**

```python
"""PostgreSQL persistence for notes."""

import os

from psycopg import AsyncConnection
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("AI_DATABASE_URL", "postgresql://ai:ai@localhost:5432/ai")


async def _conn() -> AsyncConnection:
    return await AsyncConnection.connect(DATABASE_URL, row_factory=dict_row)


async def create_note(content: str) -> dict:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO notes (content) VALUES (%s) RETURNING id, content, created_at",
                (content,),
            )
            return await cur.fetchone()


async def get_note(note_id: int) -> dict | None:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, content, created_at FROM notes WHERE id = %s", (note_id,)
            )
            return await cur.fetchone()


async def delete_note(note_id: int) -> bool:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0
```

- [ ] **Step 11: 运行确认通过**

Run: `pytest tests/test_db.py tests/test_todos.py tests/test_notes.py -v`
Expected: PASS

- [ ] **Step 12: 提交**

```bash
git add backend/database/db.py backend/database/todos.py backend/database/notes.py tests/test_db.py tests/test_todos.py tests/test_notes.py
git commit -m "feat: add todos and notes storage tables"
```

---

### Task 2: 语义层 note_memories 集合

**Files:**
- Modify: `backend/memory/semantic.py`（新增 NOTES_COLLECTION + 4 个方法）
- Modify: `backend/main.py`（lifespan 里 ensure notes collection）
- Modify: `tests/test_semantic.py`（FakeQdrant 加 delete + 新用例）

**Interfaces:**
- Consumes: `SemanticMemory`（已有 `_embed`/`_get_client`）
- Produces:
  - `semantic.ensure_notes_collection()` → None
  - `semantic.store_note(note_id: int, content: str)` → None（payload: `{note_id: str, content, created_at}`）
  - `semantic.search_notes(query: str, top_k: int = 5) -> list[dict]`（`{note_id, content, score}`）
  - `semantic.delete_note(note_id: int)` → None（按 `note_id` payload 过滤删点）

- [ ] **Step 1: 写语义层测试（先失败）**

在 `tests/test_semantic.py` 中给 `FakeQdrant` 加 `delete` 记录，并追加用例：

```python
class FakeQdrant:
    def __init__(self, collection_names=None):
        self.names = set(collection_names or [])
        self.created = []
        self.upserted = []
        self.hits = []
        self.last_search = {}
        self.deleted = []

    # ...既有 get_collections/create_collection/upsert/search 不变...

    async def delete(self, collection, points_selector):
        self.deleted.append((collection, points_selector))
```

```python
from memory.semantic import COLLECTION, NOTES_COLLECTION, SemanticMemory


async def test_ensure_notes_collection_creates_when_missing(mem):
    await mem.ensure_notes_collection()
    assert mem._client.created[0][0] == NOTES_COLLECTION


async def test_store_note_embeds_and_upserts(mem):
    await mem.store_note(42, "买咖啡豆")
    point = mem._client.upserted[0]
    assert point.payload["note_id"] == "42"
    assert point.payload["content"] == "买咖啡豆"
    assert len(point.vector) == 4


async def test_search_notes_returns_hits(mem):
    mem._client.hits = [FakeHit(score=0.9, payload={"note_id": "42", "content": "买咖啡豆"})]
    hits = await mem.search_notes("咖啡", top_k=3)
    assert hits == [{"note_id": "42", "content": "买咖啡豆", "score": 0.9}]
    assert mem._client.last_search["collection"] == NOTES_COLLECTION


async def test_delete_note_filters_by_note_id(mem):
    await mem.delete_note(42)
    coll, selector = mem._client.deleted[0]
    assert coll == NOTES_COLLECTION
    must = selector.filter.must
    assert must[0].key == "note_id"
    assert must[0].match.value == "42"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_semantic.py -v`
Expected: FAIL（`NOTES_COLLECTION` 不存在 / 方法未定义）

- [ ] **Step 3: 实现 semantic.py 扩展**

在 `semantic.py` 顶部常量处新增：

```python
NOTES_COLLECTION = "note_memories"
```

在 `SemanticMemory` 类内、`recall` 之后新增：

```python
    async def ensure_notes_collection(self) -> None:
        client = self._get_client()
        collections = await client.get_collections()
        names = {c.name for c in collections.collections}
        if NOTES_COLLECTION not in names:
            await client.create_collection(
                NOTES_COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )

    async def store_note(self, note_id: int, content: str) -> None:
        vector = self._embed([content])[0]
        point = PointStruct(
            id=uuid4().hex,
            vector=vector,
            payload={
                "note_id": str(note_id),
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await self._get_client().upsert(NOTES_COLLECTION, points=[point])

    async def search_notes(self, query: str, top_k: int = 5) -> list[dict]:
        vector = self._embed([query])[0]
        hits = await self._get_client().search(
            NOTES_COLLECTION, query_vector=vector, limit=top_k, with_payload=True
        )
        return [
            {
                "note_id": hit.payload.get("note_id", ""),
                "content": hit.payload.get("content", ""),
                "score": round(hit.score, 4),
            }
            for hit in hits
        ]

    async def delete_note(self, note_id: int) -> None:
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            FilterSelector,
            MatchValue,
        )

        client = self._get_client()
        await client.delete(
            NOTES_COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="note_id", match=MatchValue(value=str(note_id))
                        )
                    ]
                )
            ),
        )
```

- [ ] **Step 4: main.py lifespan 增加 note 集合**

在 `backend/main.py` 的 `lifespan` 里：

```python
    try:
        await semantic.ensure_collection()
        await semantic.ensure_notes_collection()
    except Exception as exc:
        logger.warning("Qdrant unavailable at startup: %s", exc)
```

- [ ] **Step 5: 运行确认通过**

Run: `pytest tests/test_semantic.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/memory/semantic.py backend/main.py tests/test_semantic.py
git commit -m "feat: add note_memories Qdrant collection with store/search/delete"
```

---

### Task 3: tools 注册表 + basic + calculator

**Files:**
- Create: `backend/tools/__init__.py`
- Create: `backend/tools/registry.py`
- Create: `backend/tools/basic.py`
- Create: `backend/tools/calculator.py`
- Create: `tests/test_calculator.py`, `tests/test_registry.py`

**Interfaces:**
- Produces:
  - `tools.registry`: `to_openai_tools() -> list[dict]`（OpenAI `tools` payload）；`async dispatch(name: str, arguments: dict) -> Any`（未知工具/异常 → `{"error": ...}`）
  - `tools.basic.now() -> dict`（`datetime/date/time/weekday`）
  - `tools.calculator.calculate(expression: str) -> dict`（`{"result": number}` 或 `{"error": ...}`）
  - `basic.now_tool`, `calculator.calculate_tool`（Tool dict，`{"name","description","parameters","handler"}`）

- [ ] **Step 1: 写 calculator 测试（先失败）**

创建 `tests/test_calculator.py`：

```python
import pytest

from tools import calculator


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("2+3*4", 14.0),
        ("(1+2)*3", 9.0),
        ("2**10", 1024.0),
        ("10/4", 2.5),
        ("7 % 3", 1.0),
        ("-5", -5.0),
        ("1.5 + 2.5", 4.0),
        ("2.0**10", 1024.0),
    ],
)
async def test_calculate_valid(expr, expected):
    assert await calculator.calculate(expression=expr) == {"result": expected}


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hi')",
        "os.system('echo hi')",
        "open('/etc/passwd')",
        "lambda: 1",
        "1; 2",
        "'abc'",
        "True",
        "a + b",
        "2**999999999999",
    ],
)
async def test_calculate_rejects_unsafe(expr):
    result = await calculator.calculate(expression=expr)
    assert "error" in result
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_calculator.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tools'`）

- [ ] **Step 3: 实现 calculator.py 与包文件**

创建 `backend/tools/__init__.py`（空文件）。

创建 `backend/tools/calculator.py`：

```python
"""Safe arithmetic evaluator for the calculate tool.

Whitelist AST nodes and evaluate recursively; never use eval/exec.
"""

import ast
import operator

ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

MAX_POW_EXPONENT = 1000


def _eval_node(node):
    if isinstance(node, ast.Constant):
        # bool 是 int 子类，需显式排除（否则 True 会被当数字 1）
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise ValueError("只支持数字运算")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        if isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant):
            if abs(node.right.value) > MAX_POW_EXPONENT:
                raise ValueError("指数过大")
        return op(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _UNOPS.get(type(node.op))
        if op is None:
            raise ValueError("不支持的运算符")
        return op(_eval_node(node.operand))
    raise ValueError("不支持的表达式")


async def calculate(expression: str) -> dict:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return {"error": "表达式语法错误"}
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            return {"error": "表达式包含不支持的语法"}
    try:
        value = _eval_node(tree.body)
    except (ZeroDivisionError, ValueError, OverflowError) as exc:
        return {"error": str(exc)}
    return {"result": value}


calculate_tool = {
    "name": "calculate",
    "description": "执行安全的数学表达式计算（四则运算、取余、乘方、括号）。需要算数或单位换算时使用。",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 '2+3*4'"}
        },
        "required": ["expression"],
    },
    "handler": calculate,
}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_calculator.py -v`
Expected: PASS

- [ ] **Step 5: 写 basic 测试 + registry 测试（先失败）**

创建 `tests/test_registry.py`：

```python
import pytest

from tools import basic
from tools import registry


async def test_now_returns_datetime_fields():
    result = await basic.now()
    assert "datetime" in result and "date" in result and "time" in result
    assert result["weekday"] in ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def test_to_openai_tools_has_all_nine():
    tools = registry.to_openai_tools()
    names = [t["function"]["name"] for t in tools]
    assert len(tools) == 9
    for expected in [
        "now", "calculate",
        "create_todo", "list_todos", "complete_todo", "delete_todo",
        "create_note", "search_notes", "delete_note",
    ]:
        assert expected in names
    first = tools[0]
    assert first["type"] == "function"
    assert "parameters" in first["function"]
    assert "description" in first["function"]


async def test_dispatch_calls_handler(monkeypatch):
    calls = []

    async def handler(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setitem(
        registry.TOOLS_BY_NAME,
        "test_tool",
        {"name": "test_tool", "description": "", "parameters": {}, "handler": handler},
    )
    assert await registry.dispatch("test_tool", {"a": 1}) == {"ok": True}
    assert calls == [{"a": 1}]


async def test_dispatch_unknown_tool_returns_error():
    result = await registry.dispatch("nope", {})
    assert "error" in result
    assert "nope" in result["error"]


async def test_dispatch_wraps_handler_exception(monkeypatch):
    async def handler(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        registry.TOOLS_BY_NAME,
        "bad",
        {"name": "bad", "description": "", "parameters": {}, "handler": handler},
    )
    result = await registry.dispatch("bad", {})
    assert "error" in result
    assert "boom" in result["error"]
```

- [ ] **Step 6: 运行确认失败**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL（registry/basic 不存在）

- [ ] **Step 7: 实现 basic.py 与 registry.py**

创建 `backend/tools/basic.py`：

```python
"""Simple built-in tools with no external dependencies."""

from datetime import datetime

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


async def now() -> dict:
    dt = datetime.now().astimezone()
    return {
        "datetime": dt.isoformat(timespec="seconds"),
        "date": dt.date().isoformat(),
        "time": dt.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS[dt.weekday()],
    }


now_tool = {
    "name": "now",
    "description": "获取当前本地日期、时间、星期。需要推算日期（如'明天''下周三'）或回答当前时间时使用。",
    "parameters": {"type": "object", "properties": {}},
    "handler": now,
}
```

创建 `backend/tools/registry.py`：

```python
"""Tool registry: schema generation and dispatch."""

from tools import basic, calculator
from tools import notes as note_tools
from tools import todo as todo_tools

ALL_TOOLS = [
    basic.now_tool,
    calculator.calculate_tool,
    todo_tools.create_todo_tool,
    todo_tools.list_todos_tool,
    todo_tools.complete_todo_tool,
    todo_tools.delete_todo_tool,
    note_tools.create_note_tool,
    note_tools.search_notes_tool,
    note_tools.delete_note_tool,
]

TOOLS_BY_NAME = {t["name"]: t for t in ALL_TOOLS}


def to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in ALL_TOOLS
    ]


async def dispatch(name: str, arguments: dict) -> dict:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"error": f"未知工具: {name}"}
    try:
        result = await tool["handler"](**arguments)
    except TypeError as exc:
        return {"error": f"工具参数错误: {exc}"}
    except Exception as exc:
        return {"error": f"工具执行失败: {exc}"}
    if result is None:
        return {"error": "工具未返回结果"}
    return result
```

> 依赖说明：`registry.py` 顶层 `from tools import todo as todo_tools` / `from tools import notes as note_tools`，这两个模块在 **Task 4** 创建。因此本任务只交付 calculator/basic 两个工具并各自跑绿；**registry 的测试与提交统一放到 Task 4**（两个任务一起交付）。

- [ ] **Step 8: 运行确认通过（calculator/basic 部分）**

Run: `pytest tests/test_calculator.py -v`
Expected: PASS

> `test_registry.py` 的验证放到 Task 4 的 Step 7/8（todo/notes 模块创建后），Task 4 统一提交 `backend/tools` 全部文件。

---

### Task 4: tools todo + notes 工具

**Files:**
- Create: `backend/tools/todo.py`
- Create: `backend/tools/notes.py`
- Create: `tests/test_todo_tools.py`, `tests/test_notes_tools.py`

**Interfaces:**
- Consumes: `database.todos`/`database.notes`（Task 1）、`semantic.store_note/search_notes/delete_note`（Task 2）
- Produces: 四个 todo 工具 dict + 三个 note 工具 dict + 对应 handler
- `registry.py`（Task 3）import 这两个模块——**Task 3 与 Task 4 一起提交**，否则 registry 导入失败

- [ ] **Step 1: 写 todo 工具测试（先失败）**

创建 `tests/test_todo_tools.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_todo_tools.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 tools/todo.py**

```python
"""Agent-facing todo tools, wrapping database.todos."""

from database import todos as todo_store


async def create_todo(title: str, due_at: str | None = None, category: str | None = None) -> dict:
    return await todo_store.create_todo(title, due_at=due_at, category=category)


async def list_todos(status: str | None = None) -> dict:
    rows = await todo_store.list_todos(status=status)
    return {"todos": rows, "count": len(rows)}


async def complete_todo(id: int) -> dict:
    return {"completed": await todo_store.complete_todo(id), "id": id}


async def delete_todo(id: int) -> dict:
    return {"deleted": await todo_store.delete_todo(id), "id": id}


create_todo_tool = {
    "name": "create_todo",
    "description": "新建一条待办事项。用户要求设置提醒、记录待办、安排任务时使用。due_at 传 ISO 8601 格式（如 2026-08-05T15:00:00）；推算日期（如'明天'）先调用 now 工具。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办内容"},
            "due_at": {"type": "string", "description": "截止时间，ISO 8601，可选"},
            "category": {"type": "string", "description": "分类，可选"},
        },
        "required": ["title"],
    },
    "handler": create_todo,
}

list_todos_tool = {
    "name": "list_todos",
    "description": "列出待办事项。用户问'我有哪些待办''明天要做什么'时使用，可按状态过滤。",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "done"], "description": "按状态过滤，可选"}
        },
    },
    "handler": list_todos,
}

complete_todo_tool = {
    "name": "complete_todo",
    "description": "把待办标记为已完成。用户说'做完了''搞定'时使用。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 id"}},
        "required": ["id"],
    },
    "handler": complete_todo,
}

delete_todo_tool = {
    "name": "delete_todo",
    "description": "删除一条待办事项。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "待办 id"}},
        "required": ["id"],
    },
    "handler": delete_todo,
}
```

- [ ] **Step 4: 写 note 工具测试（先失败）**

创建 `tests/test_notes_tools.py`：

```python
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


def test_tool_dicts_have_schemas():
    for t in [note_tools.create_note_tool, note_tools.search_notes_tool, note_tools.delete_note_tool]:
        assert t["name"]
        assert t["description"]
```

- [ ] **Step 5: 运行确认失败**

Run: `pytest tests/test_notes_tools.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 6: 实现 tools/notes.py**

```python
"""Agent-facing note tools, wrapping database.notes + semantic note memory."""

from database import notes as note_store
from memory.semantic import semantic


async def create_note(content: str) -> dict:
    note = await note_store.create_note(content)
    try:
        await semantic.store_note(note["id"], content)
    except Exception:
        pass  # 嵌入失败不阻断记录
    return note


async def search_notes(query: str, top_k: int = 5) -> dict:
    hits = await semantic.search_notes(query, top_k=top_k)
    return {"hits": hits, "count": len(hits)}


async def delete_note(id: int) -> dict:
    removed = await note_store.delete_note(id)
    try:
        await semantic.delete_note(id)
    except Exception:
        pass
    return {"deleted": removed, "id": id}


create_note_tool = {
    "name": "create_note",
    "description": "记录一条笔记/备忘。用户说'记一下''记住'时使用，把想记的内容原样写入。",
    "parameters": {
        "type": "object",
        "properties": {"content": {"type": "string", "description": "笔记内容"}},
        "required": ["content"],
    },
    "handler": create_note,
}

search_notes_tool = {
    "name": "search_notes",
    "description": "按语义搜索过往笔记/备忘。用户问'我的笔记里有关于X的吗'时使用。",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词或描述"},
            "top_k": {"type": "integer", "description": "返回条数，默认 5，可选"},
        },
        "required": ["query"],
    },
    "handler": search_notes,
}

delete_note_tool = {
    "name": "delete_note",
    "description": "删除一条笔记。",
    "parameters": {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "笔记 id"}},
        "required": ["id"],
    },
    "handler": delete_note,
}
```

- [ ] **Step 7: 运行确认通过（连同 Task 3 全部测试）**

Run: `pytest tests/test_calculator.py tests/test_registry.py tests/test_todo_tools.py tests/test_notes_tools.py -v`
Expected: PASS

- [ ] **Step 8: 提交（Task 3 + Task 4 一起）**

```bash
git add backend/tools tests/test_calculator.py tests/test_registry.py tests/test_todo_tools.py tests/test_notes_tools.py
git commit -m "feat: add todo and note tools with registry dispatch"
```

---

### Task 5: ChatAgent 事件化 + tools 参数 + 模型迁移

**Files:**
- Modify: `backend/agent/chat_agent.py`
- Modify: `tests/test_chat_agent.py`

**Interfaces:**
- Consumes: 现有 `ChatAgent`
- Produces:
  - `stream_chat(messages, memory_context=None, tools=None) -> AsyncIterator[dict]`
    - content 轮 yield `{"type": "content", "content": str}`
    - 工具选择轮 yield `{"type": "tool_call_delta", "index": int, "id": str, "name": str, "arguments": str}`
  - `DEFAULT_MODEL = "deepseek-v4-flash"`
  - 行为变化：**yield 类型从 str 改为 dict**（routes 在 Task 7 切到 orchestrator，测试同步更新）

- [ ] **Step 1: 更新测试（先失败）**

重写 `tests/test_chat_agent.py` 的事件断言与新增 tools 用例：

```python
from types import SimpleNamespace

import pytest

from agent.chat_agent import APIKeyMissingError, ChatAgent


class FakeChunk:
    def __init__(self, content=None, tool_calls=None):
        self.choices = [
            SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))
        ]


class FakeCompletions:
    def __init__(self):
        self.captured = {}

    async def create(self, **kwargs):
        self.captured.update(kwargs)

        async def _gen():
            yield FakeChunk("你")
            yield FakeChunk("好")

        return _gen()


class FakeToolChunk:
    def __init__(self, tool_calls):
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=tool_calls))]


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.chat = FakeChat()


def _tool_delta(index, id="", name="", arguments=""):
    return SimpleNamespace(
        index=index,
        id=id or None,
        function=SimpleNamespace(name=name or None, arguments=arguments),
    )


def test_validate_config_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    agent = ChatAgent()
    with pytest.raises(APIKeyMissingError):
        agent.validate_config()


@pytest.mark.asyncio
async def test_stream_chat_yields_content_events(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    events = [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}])]
    assert events == [
        {"type": "content", "content": "你"},
        {"type": "content", "content": "好"},
    ]
    captured = agent._get_client().chat.completions.captured
    assert captured["stream"] is True
    assert captured["messages"][0]["role"] == "system"
    assert captured["messages"][-1] == {"role": "user", "content": "hi"}
    assert "tools" not in captured


async def test_stream_chat_passes_tools(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    tools = [{"type": "function", "function": {"name": "now"}}]
    [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}], tools=tools)]
    captured = agent._get_client().chat.completions.captured
    assert captured["tools"] == tools


async def test_stream_chat_yields_tool_call_deltas(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    class ToolCompletions(FakeCompletions):
        async def create(self, **kwargs):
            self.captured.update(kwargs)

            async def _gen():
                yield FakeToolChunk([_tool_delta(0, id="call_1", name="create_todo", arguments="")])
                yield FakeToolChunk([_tool_delta(0, arguments='{"title": "买牛奶"}')])

            return _gen()

    class ToolChat:
        def __init__(self):
            self.completions = ToolCompletions()

    class ToolClient:
        def __init__(self, *args, **kwargs):
            self.chat = ToolChat()

    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", ToolClient)
    agent = ChatAgent()
    events = [e async for e in agent.stream_chat([{"role": "user", "content": "hi"}], tools=[{}])]
    assert events == [
        {"type": "tool_call_delta", "index": 0, "id": "call_1", "name": "create_todo", "arguments": ""},
        {"type": "tool_call_delta", "index": 0, "id": "", "name": "", "arguments": '{"title": "买牛奶"}'},
    ]


async def test_stream_chat_injects_memory_context(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr("agent.chat_agent.AsyncOpenAI", FakeClient)

    agent = ChatAgent()
    [e async for e in agent.stream_chat(
        [{"role": "user", "content": "hi"}],
        memory_context="以下是检索到的历史记忆：\n- 用户说：我喜欢咖啡",
    )]
    captured = agent._get_client().chat.completions.captured
    system = captured["messages"][0]["content"]
    assert "以下是检索到的历史记忆" in system
    assert "我喜欢咖啡" in system


async def test_default_model_is_v4_flash():
    from agent.chat_agent import DEFAULT_MODEL

    assert DEFAULT_MODEL == "deepseek-v4-flash"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_chat_agent.py -v`
Expected: FAIL（yield 仍是 str，事件断言失败；DEFAULT_MODEL 仍是 deepseek-chat）

- [ ] **Step 3: 实现 chat_agent.py 改造**

修改 `DEFAULT_MODEL`：

```python
DEFAULT_MODEL = "deepseek-v4-flash"
```

重写 `stream_chat`：

```python
    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        memory_context: str | None = None,
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        client = self._get_client()
        system = SYSTEM_PROMPT
        if memory_context:
            system = f"{system}\n\n{memory_context}"
        full_messages = [{"role": "system", "content": system}, *messages]
        kwargs: dict = {
            "model": self.model,
            "messages": full_messages,
            "stream": True,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            stream = await client.chat.completions.create(**kwargs)
        except Exception as exc:  # network / auth errors from the provider
            raise LLMError(f"调用 DeepSeek 失败: {exc}") from exc

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield {"type": "content", "content": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    function = tc.function
                    yield {
                        "type": "tool_call_delta",
                        "index": tc.index,
                        "id": tc.id or "",
                        "name": (function.name if function else "") or "",
                        "arguments": (function.arguments if function else "") or "",
                    }
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_chat_agent.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agent/chat_agent.py tests/test_chat_agent.py
git commit -m "feat: event-stream chat_agent with tools support; migrate to deepseek-v4-flash"
```

---

### Task 6: orchestrator 响应式循环

**Files:**
- Create: `backend/agent/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `agent.chat_agent.agent`、`tools.registry`（可注入）
- Produces:
  - `MAX_TOOL_ROUNDS = 5`
  - `class ToolAgent(llm=None, dispatch=registry.dispatch)`，`async stream(messages, memory_context=None) -> AsyncIterator[dict]`
    - yield `{"type": "token", "content": str}`
    - yield `{"type": "tool", "name": str, "arguments": dict, "result": Any}`

- [ ] **Step 1: 写 orchestrator 测试（先失败）**

创建 `tests/test_orchestrator.py`：

```python
import json

import pytest

from agent.orchestrator import MAX_TOOL_ROUNDS, ToolAgent


class FakeLLM:
    """Scripted per-round event streams; one list per stream_chat call."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def stream_chat(self, messages, memory_context=None, tools=None):
        self.calls.append(
            {"messages": list(messages), "memory_context": memory_context, "tools": tools}
        )
        for ev in self.rounds.pop(0):
            yield ev


def _tool_delta(idx, id_, name, args):
    return {"type": "tool_call_delta", "index": idx, "id": id_, "name": name, "arguments": args}


async def _collect(agent, messages, memory_context=None):
    return [e async for e in agent.stream(messages, memory_context=memory_context)]


async def test_roundtrip_tool_then_answer():
    fake = FakeLLM(
        [
            [_tool_delta(0, "call_1", "create_todo", ""), _tool_delta(0, "", "", '{"title": "买牛奶"}')],
            [{"type": "content", "content": "已添加待办"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        assert name == "create_todo"
        assert arguments == {"title": "买牛奶"}
        return {"id": 1, "title": "买牛奶", "status": "pending"}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "记录待办"}])

    tools = [e for e in events if e["type"] == "tool"]
    assert len(tools) == 1
    assert tools[0]["name"] == "create_todo"
    assert tools[0]["arguments"] == {"title": "买牛奶"}
    assert tools[0]["result"]["id"] == 1
    assert [e["content"] for e in events if e["type"] == "token"] == ["已添加待办"]

    # second round carries assistant tool_calls + tool result
    second = fake.calls[1]["messages"]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["id"] == "call_1"
    assert second[-1]["role"] == "tool"
    assert json.loads(second[-1]["content"])["id"] == 1
    assert fake.calls[0]["tools"], "tools payload should be passed each round"
    assert fake.calls[0]["messages"][-1] == {"role": "user", "content": "记录待办"}


async def test_passes_memory_context():
    fake = FakeLLM([[{"type": "content", "content": "hi"}]])
    agent = ToolAgent(llm=fake)
    await _collect(agent, [{"role": "user", "content": "hi"}], memory_context="记忆块")
    assert fake.calls[0]["memory_context"] == "记忆块"


async def test_multiple_parallel_tools_accumulate_by_index():
    fake = FakeLLM(
        [
            [
                _tool_delta(0, "c0", "now", "{}"),
                _tool_delta(1, "c1", "calculate", '{"expression": "2+2"}'),
            ],
            [{"type": "content", "content": "done"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        return {"ok": name}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])
    tools = [e for e in events if e["type"] == "tool"]
    assert [t["name"] for t in tools] == ["now", "calculate"]
    # 一条 assistant(tool_calls 列表) + 两条 tool 结果，按 index 顺序
    second = fake.calls[1]["messages"]
    assert [m["role"] for m in second[-4:]] == ["user", "assistant", "tool", "tool"]
    assert second[-4 + 1]["tool_calls"][0]["id"] == "c0"
    assert second[-4 + 1]["tool_calls"][1]["id"] == "c1"


async def test_round_cap_forces_final_answer():
    rounds = []
    for _ in range(MAX_TOOL_ROUNDS):
        rounds.append([_tool_delta(0, "c", "now", "{}")])
    rounds.append([{"type": "content", "content": "已达上限的答复"}])

    fake = FakeLLM(rounds)

    async def fake_dispatch(name, arguments):
        return {"ok": True}

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])

    tools = [e for e in events if e["type"] == "tool"]
    assert len(tools) == MAX_TOOL_ROUNDS
    assert [e["content"] for e in events if e["type"] == "token"] == ["已达上限的答复"]
    # cap message was appended before the final call
    assert fake.calls[-1]["messages"][-1]["content"] == "工具调用已达上限，请基于已有信息回答。"


async def test_json_parse_failure_becomes_error_result():
    fake = FakeLLM(
        [
            [_tool_delta(0, "c1", "create_todo", '{bad json')],
            [{"type": "content", "content": "处理不了"}],
        ]
    )

    async def fake_dispatch(name, arguments):
        raise AssertionError("dispatch 不应被调用")

    agent = ToolAgent(llm=fake, dispatch=fake_dispatch)
    events = await _collect(agent, [{"role": "user", "content": "x"}])
    tools = [e for e in events if e["type"] == "tool"]
    assert "error" in tools[0]["result"]
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 orchestrator.py**

```python
"""Reactive tool-calling loop that streams tokens and tool events."""

import json
from typing import Any, AsyncIterator, Callable

from agent.chat_agent import agent
from tools import registry

MAX_TOOL_ROUNDS = 5

Dispatch = Callable[[str, dict], Any]


class ToolAgent:
    def __init__(self, llm=None, dispatch: Dispatch = registry.dispatch) -> None:
        self.llm = llm or agent
        self.dispatch = dispatch

    async def stream(
        self, messages: list[dict], memory_context: str | None = None
    ) -> AsyncIterator[dict]:
        msgs = list(messages)
        for _ in range(MAX_TOOL_ROUNDS):
            tool_calls: dict[int, dict] = {}
            async for event in self.llm.stream_chat(
                msgs, memory_context=memory_context, tools=registry.to_openai_tools()
            ):
                if event["type"] == "content":
                    yield {"type": "token", "content": event["content"]}
                elif event["type"] == "tool_call_delta":
                    idx = event["index"]
                    tc = tool_calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    tc["id"] += event.get("id") or ""
                    tc["name"] += event.get("name") or ""
                    tc["arguments"] += event.get("arguments") or ""

            if not tool_calls:
                return  # 本轮回无工具调用，内容已流式产出

            assistant_tool_calls = []
            results: dict[int, Any] = {}
            for idx in sorted(tool_calls):
                tc = tool_calls[idx]
                name, args_str = tc["name"], tc["arguments"]
                try:
                    arguments = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
                    result = {"error": "工具参数不是合法 JSON"}
                else:
                    result = await self.dispatch(name, arguments)
                results[idx] = result
                yield {
                    "type": "tool",
                    "name": name,
                    "arguments": arguments,
                    "result": result,
                }
                assistant_tool_calls.append(
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": name, "arguments": args_str},
                    }
                )

            msgs.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            for idx in sorted(tool_calls):
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_calls[idx]["id"],
                        "content": json.dumps(results[idx], ensure_ascii=False),
                    }
                )

        # 轮数耗尽：强制产出最终答复
        msgs.append({"role": "user", "content": "工具调用已达上限，请基于已有信息回答。"})
        async for event in self.llm.stream_chat(
            msgs, memory_context=memory_context, tools=registry.to_openai_tools()
        ):
            if event["type"] == "content":
                yield {"type": "token", "content": event["content"]}
```

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add reactive tool-calling orchestrator"
```

---

### Task 7: routes 接入 orchestrator + POST /api/notes

**Files:**
- Modify: `backend/api/routes.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: `agent.orchestrator.ToolAgent`（模块级单例 `tool_agent`）、`database.notes`、`semantic.store_note`
- Produces:
  - `/api/chat` 产 `tool` SSE 事件 `{"type":"tool","name","arguments","result"}`
  - `POST /api/notes`，body `{content: str}` → `{id, content, created_at}`（空内容 400）
  - `agent.validate_config()` 检查保留；`tool_agent` 可在测试中 monkeypatch

- [ ] **Step 1: 更新 routes 并写新测试（先失败）**

修改 `backend/api/routes.py`：
- 顶部 import 增删：

```python
from agent.chat_agent import APIKeyMissingError, LLMError, agent
from agent.orchestrator import ToolAgent
from database import db
from database import notes as note_store
from memory.semantic import semantic
from memory.short_term import short_term
```

- 模块级单例：

```python
tool_agent = ToolAgent()
```

- 新增 Pydantic 模型：

```python
class NoteRequest(BaseModel):
    content: str
```

- `chat` 里把 `agent.stream_chat(history, memory_context=memory_block)` 换成：

```python
    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": session_id})
        parts: list[str] = []
        try:
            async for ev in tool_agent.stream(history, memory_context=memory_block):
                if ev["type"] == "token":
                    parts.append(ev["content"])
                    yield _sse("token", {"content": ev["content"]})
                elif ev["type"] == "tool":
                    yield _sse(
                        "tool",
                        {"name": ev["name"], "arguments": ev["arguments"], "result": ev["result"]},
                    )
        except LLMError as exc:
            logger.error("LLM streaming failed for session %s: %s", session_id, exc)
            yield _sse("error", {"message": str(exc)})
            return
        except Exception as exc:
            logger.exception("Unhandled streaming error for session %s", session_id)
            yield _sse("error", {"message": f"服务内部错误: {exc}"})
            return

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
```

- 新增端点（放在 chat 之后）：

```python
@router.post("/notes")
async def create_note(req: NoteRequest) -> dict:
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="内容不能为空")
    note = await note_store.create_note(content)
    try:
        await semantic.store_note(note["id"], content)
    except Exception as exc:
        logger.warning("note embed failed: %s", exc)
    return note
```

更新 `tests/test_api.py`：
- `FakeAgent` 改为 `FakeToolAgent`（提供 `stream`），fixture 的 `monkeypatch.setattr("api.routes.agent", fake_agent)` 改为 `monkeypatch.setattr("api.routes.tool_agent", fake_agent)`：

```python
class FakeToolAgent:
    def __init__(self, events=None):
        self.last_messages = None
        self.last_memory_context = None
        self.events = events or [
            {"type": "token", "content": "你"},
            {"type": "token", "content": "好"},
        ]

    async def stream(self, messages, memory_context=None):
        self.last_messages = messages
        self.last_memory_context = memory_context
        for ev in self.events:
            yield ev
```

- 新增用例：

```python
def test_chat_emits_tool_event(ctx):
    ctx["agent"].events = [
        {"type": "tool", "name": "create_todo", "arguments": {"title": "买牛奶"}, "result": {"id": 1}},
        {"type": "token", "content": "已添加"},
    ]
    res = ctx["client"].post("/api/chat", json={"message": "记录待办"})
    assert res.status_code == 200
    assert '"type": "tool"' in res.text
    assert '"create_todo"' in res.text
    assert '"type": "token"' in res.text


def test_create_note_endpoint(ctx, monkeypatch):
    async def fake_create(content):
        return {"id": 3, "content": content, "created_at": "2026-08-04T10:00:00+00:00"}

    async def fake_store(note_id, content):
        pass

    monkeypatch.setattr("api.routes.note_store.create_note", fake_create)
    monkeypatch.setattr("api.routes.semantic.store_note", fake_store)
    res = ctx["client"].post("/api/notes", json={"content": "买咖啡豆"})
    assert res.status_code == 200
    assert res.json()["content"] == "买咖啡豆"
    assert res.json()["id"] == 3


def test_create_note_empty_returns_400(ctx):
    res = ctx["client"].post("/api/notes", json={"content": "   "})
    assert res.status_code == 400
```

注意：现有测试里 `ctx["agent"].last_messages` / `.last_memory_context` 断言仍成立（FakeToolAgent 记录同名属性）。

- 在 `ctx` fixture 里，`semantic.ensure_collection` 的 noop 旁补一行 `ensure_notes_collection` 的 noop（否则 lifespan 里新增的 `ensure_notes_collection()` 会真连 Qdrant 拖慢/失败）：

```python
    monkeypatch.setattr(semantic, "ensure_collection", _noop)
    monkeypatch.setattr(semantic, "ensure_notes_collection", _noop)
```

`test_startup_survives_qdrant_down` 无需改：它让 `ensure_collection` 抛错，`ensure_notes_collection` 不会被执行到。

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_api.py -v`
Expected: FAIL（`api.routes.tool_agent` 尚不存在）

- [ ] **Step 3: 按 Step 1 实现 routes.py**

应用上述四处改动（imports、单例、chat 循环、notes 端点）。

- [ ] **Step 4: 运行确认通过**

Run: `pytest tests/test_api.py tests/test_orchestrator.py tests/test_chat_agent.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/api/routes.py tests/test_api.py
git commit -m "feat: wire orchestrator into chat; add POST /api/notes"
```

---

### Task 8: 前端 — 工具卡片 + 记笔记按钮

**Files:**
- Modify: `backend/static/index.html`

**Interfaces:**
- Consumes: `/api/chat` 的 `tool` 事件、`POST /api/notes`
- 无自动化测试（静态页面），手动验证

- [ ] **Step 1: 加工具卡片样式**

在 `<style>` 里追加：

```css
.tool-call {
  align-self: flex-start;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--muted);
  max-width: 78%;
}
.tool-result {
  margin-top: 4px;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
}
```

- [ ] **Step 2: 加记笔记按钮**

`<footer>` 里，`#send` 按钮前加：

```html
<button id="note-btn" title="把当前输入记成笔记">记笔记</button>
```

- [ ] **Step 3: 加工具卡片渲染 + 按钮逻辑**

在 `<script>` 里 `addMessage` 之后加：

```js
function addToolCard(ev) {
  const div = document.createElement("div");
  div.className = "tool-call";
  const args = JSON.stringify(ev.arguments || {});
  const head = document.createElement("div");
  head.textContent = "工具调用 " + ev.name + "(" + args + ")";
  const result = document.createElement("div");
  result.className = "tool-result";
  result.textContent = typeof ev.result === "string" ? ev.result : JSON.stringify(ev.result, null, 2);
  div.appendChild(head);
  div.appendChild(result);
  main.appendChild(div);
  main.scrollTop = main.scrollHeight;
}
```

在 `consumeSSE` 的 `onEvent` 里、`done` 分支前加：

```js
} else if (ev.type === "tool") {
  addToolCard(ev);
}
```

在 `sendBtn.addEventListener` 之后加：

```js
const noteBtn = document.getElementById("note-btn");
noteBtn.addEventListener("click", async () => {
  const text = input.value.trim();
  if (!text || noteBtn.disabled) return;
  noteBtn.disabled = true;
  try {
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: text }),
    });
    if (res.ok) {
      input.value = "";
      addMessage("assistant", "已记录到笔记");
    } else {
      addMessage("error", "记录失败");
    }
  } catch (e) {
    addMessage("error", "记录失败: " + e.message);
  } finally {
    noteBtn.disabled = false;
  }
});
```

- [ ] **Step 4: 手动验证**

`docker compose up -d --build` 后浏览器打开 http://localhost:8000：
1. 发"记下：明天下班买咖啡豆" → 出现"工具调用 create_note(...)"卡片 + 最终答复
2. 输入框输入任意文本，点"记笔记" → 出现"已记录到笔记"
3. 新会话问"我的备忘里关于咖啡的" → 出现 search_notes 工具卡片 + 召回内容

- [ ] **Step 5: 提交**

```bash
git add backend/static/index.html
git commit -m "feat: render tool-call cards and add note-record button in web chat"
```

---

### Task 9: 配置 + 记忆 + 集成验证

**Files:**
- Modify: `.env.example`（`DEEPSEEK_MODEL=deepseek-v4-flash`）
- Modify: `.env`（本地同 key 值；含 API key，仅本地改）
- Modify: `docs/superpowers/specs/2026-08-04-phase3-agent-design.md`（无；已含）
- Modify: 记忆文件 `C:\Users\gry\.claude\projects\C--Users-gry-program-personal-ai\memory\project_personal_ai.md`

**Interfaces:**
- 无代码接口，纯配置/文档/验证

- [ ] **Step 1: 更新模型配置**

`.env.example`：
```
DEEPSEEK_MODEL=deepseek-v4-flash
```
本地 `.env` 同步（把 `DEEPSEEK_MODEL` 改为 `deepseek-v4-flash`；若值缺失则新增）。

`backend/api/routes.py` 的 `health` 里默认模型名同步：

```python
"model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
```

- [ ] **Step 2: 全量单测**

Run: `pytest -v`
Expected: 全部 PASS（含既有 test_short_term/test_db 等）

- [ ] **Step 3: 集成验证（docker compose）**

Run: `docker compose up -d --build`（首次会经 1ms.run 拉 `python:3.12-slim`，模型已烘焙不需联网）

验证场景（每一条都要实际跑通）：
1. 重启容器后问之前聊过的事 → 上下文恢复（Phase 2 回归）
2. "现在几点了？" → now 工具卡片 + 当前时间
3. "帮我算 15% 的 780" → calculate 卡片 + 117
4. "记下：明天下班买咖啡豆" → create_note 卡片；`docker compose exec postgres psql -U ai -d ai -c "select * from notes"` 有记录
5. "我有哪些待办？" → list_todos 卡片（空列表也要正常回复）
6. "明天下午3点提醒我开会" → now（算日期）+ create_todo 两张卡片
7. 新会话"搜我的备忘里关于咖啡的" → search_notes 卡片召回
8. 点"记笔记"按钮直录 → notes 表 + Qdrant `note_memories` 都有
9. `/api/health` 返回 `"model": "deepseek-v4-flash"`

- [ ] **Step 4: 更新记忆**

更新 `project_personal_ai.md`：状态改为 Phase 3 完成（或进行中），补充工具清单、`deepseek-v4-flash` 模型名、note_memories 集合。

- [ ] **Step 5: 提交**

```bash
git add .env.example backend/api/routes.py docs/superpowers/specs/2026-08-04-phase3-agent-design.md
git commit -m "chore: migrate to deepseek-v4-flash; document Phase 3"
```

---

## Self-Review 结果

（书写计划时自查，已内联修正，无需另行操作）

- **Spec 覆盖**：9 工具 ✓、响应式循环 ✓、SSE tool 事件 ✓、/api/notes + UI 直录按钮 ✓、note_memories 同步 ✓、错误处理 ✓、模型迁移 ✓、测试（单元+集成）✓
- **占位符**：无 TBD/TODO；所有代码步骤均含实际实现
- **类型一致性**：`stream_chat` 事件 dict、orchestrator 事件 dict、registry dispatch、storage 签名在 Task 间对齐；Task 6 orchestrator 用 `results` 缓存避免同一工具执行两次
- **内联修正清单**：
  - Task 6：去掉 `_result_for` 重复执行版本，只留一份 `results` 缓存版 `stream`
  - Task 3：registry 依赖 Task 4 的 todo/notes 模块 → 验证与提交合并到 Task 4
  - Task 3 calculator：删除 `("2**1000", float(2**1000))`（int 与 float 精确比较不相等）；`_eval_node` 显式排除 `bool`（`True` 是 int 子类会被当数字 1）
  - Task 6 并行工具测试：一轮两个并行工具产生 `[user, assistant(tool_calls), tool, tool]`，断言序列修正
  - Task 7：ctx fixture 补 `ensure_notes_collection` noop，避免 lifespan 真连 Qdrant
