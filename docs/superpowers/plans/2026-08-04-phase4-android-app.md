# Phase 4 Android App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一个 Flutter 安卓 App（真机跑在小米澎湃系统），包含聊天（SSE 流式 + 工具卡片 + 记笔记按钮 + 会话恢复）、待办页（全 CRUD）、笔记页（列表 + 语义搜索 + 删除），后端只新增 REST 接口，复用现有 database 层。

**Architecture:** monorepo 新增 `app/`（Flutter，依赖仅 provider/http/shared_preferences）与 `backend/` 平级。后端在 `api/routes.py` 加 todos/notes 的 REST 端点（复用 `database.todos`/`database.notes` + `tools.jsonable_row`），`database/notes.py` 补一个 `list_notes`。App 三层：services（SSE 手写解析 + REST）+ state（ChangeNotifier controller）+ screens（聊天/待办/笔记/设置）。自动化验证只用主机侧 `flutter test` + `flutter analyze`（无需 Android SDK）；APK 构建/真机安装为用户手动步骤（Task 11 给指引）。

**Tech Stack:** Flutter 3.44.8 stable（Windows zip）、Dart 3、`provider`、`http`、`shared_preferences`、FastAPI（现有）、pytest（现有）。

## Global Constraints

- 平台：Flutter Android App，真机跑在小米澎湃系统（HyperOS）。本机**无 Android SDK/Java**——自动化验证只用主机侧 `flutter test` + `flutter analyze`（不需要 Android SDK）；APK 构建与真机安装是用户手动步骤。
- Flutter SDK：stable **3.44.8**，解压到 `C:\Users\gry\program\flutter`（仓库外，不提交）。git-bash 里统一用 `FLUTTER=/c/Users/gry/program/flutter/bin/flutter`（bash 状态不跨命令持久，不要依赖 PATH）。
- monorepo：新增 `app/` 与 `backend/` 平级。后端**只加 REST 接口**，复用 `database.todos`/`database.notes` + `tools.jsonable_row`（datetime→ISO 字符串）。
- REST 契约（verbatim，来自 spec §3）：
  | 接口 | 成功返回 | 错误 |
  |---|---|---|
  | `GET /api/todos?status=` | `{"todos":[{id,title,status,category,due_at,created_at,completed_at}...],"count":n}` | — |
  | `POST /api/todos` `{title,due_at?,category?}` | 新行（jsonable_row） | 400 空标题 |
  | `POST /api/todos/{id}/complete` | `{"completed":true,"id":id}` | 404 不存在 |
  | `DELETE /api/todos/{id}` | `{"deleted":true,"id":id}` | 404 不存在 |
  | `GET /api/notes` | `{"notes":[{id,content,created_at}...],"count":n}` | — |
  | `GET /api/notes/search?q=&top_k=5` | `{"hits":[{note_id,content,score}...],"count":n}` | 400 空 q |
  | `DELETE /api/notes/{id}` | `{"deleted":true,"id":id}` | 404 不存在 |
- 错误细节文案：空标题 → `标题不能为空`；空 q → `搜索词不能为空`。
- 后端字段名保持 snake_case（`due_at`/`created_at`/`completed_at`/`note_id`），App 模型做映射。
- Flutter 运行时依赖**只允许 3 个**：`provider`、`http`、`shared_preferences`（dev：`flutter_test`、`flutter_lints`）。SSE **不引第三方包**：用 `dart:io` HttpClient + LineSplitter，解析器提成纯函数 `parseSseLine(String) → ChatEvent?` 以便单测。
- 默认服务器地址：`http://10.0.2.2:8000`（安卓模拟器指向宿主机；真机改为电脑局域网 IP，设置页可改）。
- Android 9+ 默认禁明文 HTTP：`app/android/app/src/main/AndroidManifest.xml` 的 `<application>` 设 `android:usesCleartextTraffic="true"`。
- 不做（YAGNI）：登录/鉴权、外网/HTTPS/云部署、桌面端/Web 前端、待办定时推送、第三方 SSE 包、重型状态管理。
- 测试命令（git-bash，仓库根 `/c/Users/gry/program/personal_ai`）：
  - 后端：`.venv/Scripts/python -m pytest tests/test_xxx.py -v`
  - Flutter：`cd app && /c/Users/gry/program/flutter/bin/flutter test test/xxx_test.dart`
- Commit：conventional commits，中文说明，参照仓库历史风格（feat:/fix:/refactor:/chore:/docs:）。

---

### Task 1: 后端 todos REST 接口

**Files:**
- Modify: `backend/api/routes.py`（加 import + `TodoCreate` + 4 个端点）
- Test: `tests/test_todo_api.py`（新建）

**Interfaces:**
- Consumes: `database.todos`（create_todo/list_todos/complete_todo/delete_todo，签名见 backend/database/todos.py）、`tools.jsonable_row(row: dict) -> dict`
- Produces: 端点 `GET /api/todos`、`POST /api/todos`、`POST /api/todos/{id}/complete`、`DELETE /api/todos/{id}`（Task 9 的待办页依赖）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_todo_api.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_todo_api.py -v`
Expected: FAIL——`api.routes` 没有 `todo_store` 属性（ImportError / AttributeError）。

- [ ] **Step 3: 实现最小代码**

在 `backend/api/routes.py`：

1. 顶部 import 区加一行：

```python
from database import todos as todo_store
```

2. 在文件末尾（`create_note` 端点之后）追加：

```python
class TodoCreate(BaseModel):
    title: str
    due_at: str | None = None
    category: str | None = None


@router.get("/todos")
async def list_todos(status: str | None = None) -> dict:
    rows = await todo_store.list_todos(status=status)
    return {"todos": [jsonable_row(r) for r in rows], "count": len(rows)}


@router.post("/todos")
async def create_todo(req: TodoCreate) -> dict:
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")
    row = await todo_store.create_todo(title, due_at=req.due_at, category=req.category)
    return jsonable_row(row)


@router.post("/todos/{todo_id}/complete")
async def complete_todo(todo_id: int) -> dict:
    ok = await todo_store.complete_todo(todo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"completed": True, "id": todo_id}


@router.delete("/todos/{todo_id}")
async def delete_todo(todo_id: int) -> dict:
    ok = await todo_store.delete_todo(todo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="待办不存在")
    return {"deleted": True, "id": todo_id}
```

注意：`routes.py` 里已有路由函数名 `create_note`，新函数名 `create_todo`/`list_todos`/`complete_todo`/`delete_todo` 不与现有函数冲突。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_todo_api.py -v`
Expected: 9 passed。

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 原有 91 个 + 新增 9 个全部通过。

```bash
git add backend/api/routes.py tests/test_todo_api.py
git commit -m "feat: add todos REST endpoints"
```

---

### Task 2: 后端 notes REST 接口 + database.list_notes

**Files:**
- Modify: `backend/database/notes.py`（加 `list_notes`）
- Modify: `backend/api/routes.py`（加 3 个端点）
- Test: `tests/test_notes.py`（加一个 list_notes 测试）、`tests/test_note_api.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `jsonable_row`/`HTTPException`/`BaseModel` 用法；`database.notes`（现有 create_note/get_note/delete_note）、`semantic.search_notes(query, top_k=5)`（backend/memory/semantic.py，返回 `[{"note_id": str, "content": str, "score": float}]`）
- Produces: `database.notes.list_notes(limit=50) -> list[dict]`；端点 `GET /api/notes`、`GET /api/notes/search`、`DELETE /api/notes/{id}`（Task 10 的笔记页依赖）

- [ ] **Step 1: 写失败测试**

`backend/database/notes.py` 加 `list_notes`；在 `tests/test_notes.py`（已有 `fake_conn` fixture，见文件头）末尾追加：

```python
async def test_list_notes_returns_rows(fake_conn):
    fake_conn["conn"] = FakeConn(
        fetchall_results=[{"id": 1, "content": "买牛奶", "created_at": "2026-08-04T10:00:00+00:00"}]
    )
    rows = await notes.list_notes()
    assert rows[0]["content"] == "买牛奶"
    sql, params = fake_conn["conn"].cursor_obj.statements[0]
    assert "ORDER BY id DESC" in sql
    assert params == (50,)
```

创建 `tests/test_note_api.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_notes.py tests/test_note_api.py -v`
Expected: FAIL——`notes.list_notes` 不存在（AttributeError）且 `api.routes.note_store.list_notes` 不存在。

- [ ] **Step 3: 实现最小代码**

`backend/database/notes.py` 末尾追加：

```python
async def list_notes(limit: int = 50) -> list[dict]:
    async with await _conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return await cur.fetchall()
```

`backend/api/routes.py` 末尾（Task 1 的 todos 端点之后）追加：

```python
@router.get("/notes")
async def list_notes() -> dict:
    rows = await note_store.list_notes()
    return {"notes": [jsonable_row(r) for r in rows], "count": len(rows)}


@router.get("/notes/search")
async def search_notes(q: str, top_k: int = 5) -> dict:
    q = q.strip()
    if not q:
        raise HTTPException(status_code=400, detail="搜索词不能为空")
    hits = await semantic.search_notes(q, top_k=top_k)
    return {"hits": hits, "count": len(hits)}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int) -> dict:
    ok = await note_store.delete_note(note_id)
    if not ok:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return {"deleted": True, "id": note_id}
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_notes.py tests/test_note_api.py -v`
Expected: 全部通过（原 test_notes.py 3 个 + 新增 7 个）。

- [ ] **Step 5: 全量回归 + 提交**

Run: `.venv/Scripts/python -m pytest -q`
Expected: 全部通过（100 个）。

```bash
git add backend/database/notes.py backend/api/routes.py tests/test_notes.py tests/test_note_api.py
git commit -m "feat: add notes list/search/delete REST endpoints"
```

---

### Task 3: Flutter 工具链 + 项目脚手架

**Files:**
- Create: `app/`（`flutter create` 生成，含 `app/android/`、`app/lib/`、`app/test/`、`app/pubspec.yaml`、`app/.gitignore`）
- Modify: `app/pubspec.yaml`（依赖）、`app/android/app/src/main/AndroidManifest.xml`（cleartext）
- Modify: `app/test/widget_test.dart`（换成 smoke test）

**Interfaces:**
- Consumes: Flutter SDK 3.44.8（本 Task 安装）；pub.dev / Google storage 已确认可达
- Produces: 可运行 `flutter test`/`flutter analyze` 的 `app/` 工程（后续 Task 4-11 的基地）；固定 SDK 路径 `/c/Users/gry/program/flutter/bin/flutter`

- [ ] **Step 1: 下载并解压 Flutter SDK 3.44.8**

Run（git-bash）：

```bash
mkdir -p /c/Users/gry/program/flutter
cd /tmp
curl -fL --max-time 900 -o flutter.zip \
  https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_3.44.8-stable.zip
unzip -q flutter.zip -d /c/Users/gry/program/flutter_tmp
mv /c/Users/gry/program/flutter_tmp/flutter/* /c/Users/gry/program/flutter/
rmdir /c/Users/gry/program/flutter_tmp/flutter /c/Users/gry/program/flutter_tmp 2>/dev/null || true
rm -f /tmp/flutter.zip
```

Expected: `/c/Users/gry/program/flutter/bin/flutter` 存在。

- [ ] **Step 2: 首次运行初始化 + 关闭 analytics**

Run:

```bash
export FLUTTER_SUPPRESS_ANALYTICS=true
/c/Users/gry/program/flutter/bin/flutter --disable-analytics >/dev/null 2>&1 || true
/c/Users/gry/program/flutter/bin/flutter config --no-analytics >/dev/null 2>&1 || true
/c/Users/gry/program/flutter/bin/flutter --version
```

Expected: 输出 Flutter 3.44.8（首次会自解压 Dart SDK，可能耗时几分钟）。不要运行 `flutter doctor`（会因缺 Android SDK 报红，可忽略——本计划不需要它）。

- [ ] **Step 3: flutter create 脚手架**

Run（仓库根 `/c/Users/gry/program/personal_ai`）：

```bash
/c/Users/gry/program/flutter/bin/flutter create \
  --project-name personal_ai_app \
  --org com.personalai \
  --platforms android \
  app
```

Expected: 生成 `app/`。若提示缺 Android toolchain，忽略（只警告，不失败）。

- [ ] **Step 4: 配依赖 + 打开明文 HTTP + 换 smoke test**

`app/pubspec.yaml` 的 `dependencies:` 段替换为：

```yaml
dependencies:
  flutter:
    sdk: flutter
  provider: ^6.1.2
  http: ^1.2.2
  shared_preferences: ^2.3.2
```

（`dev_dependencies` 保持默认的 `flutter_test` + `flutter_lints`。）

`app/android/app/src/main/AndroidManifest.xml`：在 `<application` 标签上加 `android:usesCleartextTraffic="true"`，即：

```xml
<application
    android:label="personal_ai_app"
    android:name="${applicationName}"
    android:icon="@mipmap/ic_launcher"
    android:usesCleartextTraffic="true">
```

（保留该文件其余内容不变。）

把 `app/test/widget_test.dart` 整体替换为：

```dart
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('脚手架可运行', () {
    expect(1 + 1, 2);
  });
}
```

- [ ] **Step 5: 拉依赖 + 跑 smoke test + analyze**

Run:

```bash
cd /c/Users/gry/program/personal_ai/app
export FLUTTER_SUPPRESS_ANALYTICS=true
/c/Users/gry/program/flutter/bin/flutter pub get
/c/Users/gry/program/flutter/bin/flutter test
/c/Users/gry/program/flutter/bin/flutter analyze
```

Expected: test 1 passed；analyze 无 issue。

- [ ] **Step 6: 提交**

```bash
git add app
git commit -m "chore: scaffold Flutter android app with minimal deps"
```

---

### Task 4: App 基础 —— models + SSE 解析器 + 单元测试

**Files:**
- Create: `app/lib/models/todo.dart`、`app/lib/models/note.dart`、`app/lib/models/chat_message.dart`
- Create: `app/lib/services/chat_service.dart`（本 Task 先只写 `parseSseLine` 与事件类；`ChatService.stream` 在 Task 5 补全）
- Test: `app/test/models_test.dart`、`app/test/sse_parser_test.dart`

**Interfaces:**
- Consumes: Task 3 的 `app/` 工程
- Produces: `Todo`/`Note`/`ChatBubble`（含 `BubbleKind` 枚举）、SSE 事件类（`SessionEvent`/`TokenEvent`/`ToolEvent`/`ErrorEvent`/`DoneEvent`，都是 `ChatEvent` 子类）、纯函数 `ChatEvent? parseSseLine(String line)`（Task 5 的 ChatService、Task 8 的聊天页依赖）

- [ ] **Step 1: 写失败测试**

`app/test/models_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/chat_message.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/models/todo.dart';

void main() {
  test('Todo.fromJson 映射后端字段', () {
    final t = Todo.fromJson({
      'id': 1,
      'title': '买牛奶',
      'status': 'pending',
      'category': '购物',
      'due_at': '2026-08-05T15:00:00+08:00',
      'created_at': '2026-08-04T10:00:00+00:00',
      'completed_at': null,
    });
    expect(t.id, 1);
    expect(t.title, '买牛奶');
    expect(t.status, 'pending');
    expect(t.category, '购物');
    expect(t.dueAt, '2026-08-05T15:00:00+08:00');
    expect(t.isDone, isFalse);
  });

  test('Note.fromListJson', () {
    final n = Note.fromListJson({
      'id': 2,
      'content': '买咖啡豆',
      'created_at': '2026-08-04T10:00:00+00:00',
    });
    expect(n.id, 2);
    expect(n.content, '买咖啡豆');
    expect(n.score, isNull);
  });

  test('Note.fromSearchJson 用 note_id', () {
    final n = Note.fromSearchJson({'note_id': '2', 'content': '明天下班买咖啡豆', 'score': 0.87});
    expect(n.id, 2);
    expect(n.score, 0.87);
  });

  test('ChatBubble 各 kind', () {
    expect(ChatBubble(kind: BubbleKind.user, content: 'hi').kind, BubbleKind.user);
    final tool = ChatBubble(kind: BubbleKind.tool, name: 'now', arguments: const {}, result: const {'datetime': 'x'});
    expect(tool.name, 'now');
    expect(tool.result, const {'datetime': 'x'});
  });
}
```

`app/test/sse_parser_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/services/chat_service.dart';

void main() {
  test('解析 session 事件', () {
    final ev = parseSseLine('data: {"type":"session","session_id":"abc"}');
    expect(ev, isA<SessionEvent>());
    expect((ev as SessionEvent).sessionId, 'abc');
  });

  test('解析 token 事件', () {
    final ev = parseSseLine('data: {"type":"token","content":"你好"}');
    expect(ev, isA<TokenEvent>());
    expect((ev as TokenEvent).content, '你好');
  });

  test('解析 tool 事件', () {
    final ev = parseSseLine(
        'data: {"type":"tool","name":"create_todo","arguments":{"title":"买牛奶"},"result":{"id":1}}');
    expect(ev, isA<ToolEvent>());
    final t = ev as ToolEvent;
    expect(t.name, 'create_todo');
    expect(t.arguments['title'], '买牛奶');
    expect(t.result['id'], 1);
  });

  test('解析 error 与 done', () {
    expect((parseSseLine('data: {"type":"error","message":"炸了"}') as ErrorEvent).message, '炸了');
    expect(parseSseLine('data: {"type":"done"}'), isA<DoneEvent>());
  });

  test('非 data 行 / 非 JSON / 未知类型返回 null', () {
    expect(parseSseLine(''), isNull);
    expect(parseSseLine('data: not-json'), isNull);
    expect(parseSseLine('data: {"type":"weird"}'), isNull);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/models_test.dart test/sse_parser_test.dart`
Expected: FAIL——import 找不到 `models/todo.dart` 等（编译错误）。

- [ ] **Step 3: 实现最小代码**

`app/lib/models/todo.dart`：

```dart
class Todo {
  Todo({
    required this.id,
    required this.title,
    this.status = 'pending',
    this.category,
    this.dueAt,
    this.createdAt,
    this.completedAt,
  });

  final int id;
  final String title;
  final String status;
  final String? category;
  final String? dueAt;
  final String? createdAt;
  final String? completedAt;

  bool get isDone => status == 'done';

  factory Todo.fromJson(Map<String, dynamic> json) => Todo(
        id: json['id'] as int,
        title: json['title'] as String,
        status: (json['status'] as String?) ?? 'pending',
        category: json['category'] as String?,
        dueAt: json['due_at'] as String?,
        createdAt: json['created_at'] as String?,
        completedAt: json['completed_at'] as String?,
      );
}
```

`app/lib/models/note.dart`：

```dart
class Note {
  Note({required this.id, required this.content, this.createdAt, this.score});

  final int id;
  final String content;
  final String? createdAt;
  final double? score;

  factory Note.fromListJson(Map<String, dynamic> json) => Note(
        id: json['id'] as int,
        content: json['content'] as String,
        createdAt: json['created_at'] as String?,
      );

  factory Note.fromSearchJson(Map<String, dynamic> json) => Note(
        id: int.tryParse((json['note_id'] as String?) ?? '') ?? 0,
        content: (json['content'] as String?) ?? '',
        score: (json['score'] as num?)?.toDouble(),
      );
}
```

`app/lib/models/chat_message.dart`：

```dart
enum BubbleKind { user, assistant, tool, error }

class ChatBubble {
  ChatBubble({
    required this.kind,
    this.content = '',
    this.name,
    this.arguments,
    this.result,
  });

  final BubbleKind kind;
  String content;
  final String? name;
  final Map<String, dynamic>? arguments;
  final Map<String, dynamic>? result;
}
```

`app/lib/services/chat_service.dart`（先定义事件类 + 纯函数；`ChatService` 类本体 Task 5 追加）：

```dart
sealed class ChatEvent {}

class SessionEvent extends ChatEvent {
  SessionEvent(this.sessionId);
  final String sessionId;
}

class TokenEvent extends ChatEvent {
  TokenEvent(this.content);
  final String content;
}

class ToolEvent extends ChatEvent {
  ToolEvent({required this.name, required this.arguments, required this.result});
  final String name;
  final Map<String, dynamic> arguments;
  final Map<String, dynamic> result;
}

class ErrorEvent extends ChatEvent {
  ErrorEvent(this.message);
  final String message;
}

class DoneEvent extends ChatEvent {}

import 'dart:convert';

ChatEvent? parseSseLine(String line) {
  if (!line.startsWith('data: ')) return null;
  final Map<String, dynamic> payload;
  try {
    payload = jsonDecode(line.substring(6)) as Map<String, dynamic>;
  } on FormatException {
    return null;
  }
  return switch (payload['type']) {
    'session' => SessionEvent(payload['session_id'] as String),
    'token' => TokenEvent(payload['content'] as String),
    'tool' => ToolEvent(
        name: payload['name'] as String,
        arguments: (payload['arguments'] as Map?)?.cast<String, dynamic>() ?? const {},
        result: (payload['result'] as Map?)?.cast<String, dynamic>() ?? const {},
      ),
    'error' => ErrorEvent(payload['message'] as String),
    'done' => DoneEvent(),
    _ => null,
  };
}
```

注意：`import 'dart:convert';` 放在文件顶部（不要放在类定义中间）。

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/models_test.dart test/sse_parser_test.dart`
Expected: 全过（9 个）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib app/test
git commit -m "feat: add todo/note/chat models and SSE line parser"
```

---

### Task 5: App 服务层 —— settings / api / chat services

**Files:**
- Modify: `app/lib/services/chat_service.dart`（加 `ChatService` 类）
- Create: `app/lib/services/settings_service.dart`、`app/lib/services/api_client.dart`
- Test: `app/test/settings_service_test.dart`、`app/test/api_client_test.dart`

**Interfaces:**
- Consumes: Task 4 的 `ChatEvent` 系列 + `parseSseLine`；`Todo`/`Note` 模型
- Produces: `SettingsService`（serverUrl + load/setServerUrl）、`ApiClient`（`baseUrl` 可变 + 8 个 REST 方法 + `ApiException`）、`ChatService`（`baseUrl` 可变 + `Stream<ChatEvent> stream(String message, String? sessionId)`）。Task 6-11 全部依赖。

- [ ] **Step 1: 写失败测试**

`app/test/settings_service_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('未保存过时用默认地址', () async {
    final s = SettingsService();
    await s.load();
    expect(s.serverUrl, 'http://10.0.2.2:8000');
  });

  test('保存后新实例加载仍生效', () async {
    final s = SettingsService();
    await s.load();
    await s.setServerUrl('http://192.168.1.10:8000');

    final t = SettingsService();
    await t.load();
    expect(t.serverUrl, 'http://192.168.1.10:8000');
  });
}
```

`app/test/api_client_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_ai_app/services/api_client.dart';

ApiClient clientWith(String body, int status) => ApiClient(
      baseUrl: 'http://test',
      client: MockClient(
        (req) async => http.Response(body, status, headers: {'content-type': 'application/json'}),
      ),
    );

void main() {
  test('listTodos 解析列表', () async {
    final api = clientWith(
      '{"todos":[{"id":1,"title":"买牛奶","status":"pending","category":null,"due_at":null,"created_at":"2026-08-04T10:00:00+00:00","completed_at":null}],"count":1}',
      200,
    );
    final todos = await api.listTodos();
    expect(todos.single.title, '买牛奶');
  });

  test('createTodo 发送 title/category', () async {
    late http.Request captured;
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        captured = req;
        return http.Response('{"id":1,"title":"买牛奶","status":"pending","category":"购物"}', 200,
            headers: {'content-type': 'application/json'});
      }),
    );
    await api.createTodo(title: '买牛奶', category: '购物');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/api/todos');
    expect(captured.body, contains('买牛奶'));
  });

  test('非 2xx 抛 ApiException 并带 detail', () async {
    final api = clientWith('{"detail":"标题不能为空"}', 400);
    expect(
      () => api.createTodo(title: ''),
      throwsA(isA<ApiException>().having((e) => e.message, 'message', '标题不能为空')),
    );
  });

  test('searchNotes 解析 hits（note_id 为字符串）', () async {
    final api = clientWith('{"hits":[{"note_id":"2","content":"明天下班买咖啡豆","score":0.87}],"count":1}', 200);
    final hits = await api.searchNotes('咖啡');
    expect(hits.single.id, 2);
    expect(hits.single.score, 0.87);
  });

  test('listNotes 解析列表', () async {
    final api = clientWith(
      '{"notes":[{"id":1,"content":"买咖啡豆","created_at":"2026-08-04T10:00:00+00:00"}],"count":1}',
      200,
    );
    final notes = await api.listNotes();
    expect(notes.single.content, '买咖啡豆');
  });

  test('deleteNote / completeTodo 打到对应路径', () async {
    final paths = <String>[];
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        paths.add('${req.method} ${req.url.path}');
        return http.Response('{"deleted":true,"id":2}', 200, headers: {'content-type': 'application/json'});
      }),
    );
    await api.deleteNote(2);
    await api.completeTodo(5);
    expect(paths, ['DELETE /api/notes/2', 'POST /api/todos/5/complete']);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/settings_service_test.dart test/api_client_test.dart`
Expected: FAIL——`SettingsService`/`ApiClient` 未定义。

- [ ] **Step 3: 实现最小代码**

`app/lib/services/settings_service.dart`：

```dart
import 'package:shared_preferences/shared_preferences.dart';

class SettingsService {
  static const _keyServerUrl = 'serverUrl';
  static const defaultServerUrl = 'http://10.0.2.2:8000';

  String serverUrl = defaultServerUrl;

  Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    serverUrl = prefs.getString(_keyServerUrl) ?? defaultServerUrl;
  }

  Future<void> setServerUrl(String url) async {
    serverUrl = url;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyServerUrl, url);
  }
}
```

`app/lib/services/api_client.dart`：

```dart
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/note.dart';
import '../models/todo.dart';

class ApiException implements Exception {
  ApiException(this.message);
  final String message;

  @override
  String toString() => message;
}

class ApiClient {
  ApiClient({required this.baseUrl, http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String baseUrl;

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$baseUrl/api$path').replace(queryParameters: query);

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Object? body,
    Map<String, String>? query,
  }) async {
    final req = http.Request(method, _uri(path, query));
    if (body != null) {
      req.headers['content-type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    final streamed = await _client.send(req);
    final res = await http.Response.fromStream(streamed);
    final decoded = res.body.isEmpty
        ? <String, dynamic>{}
        : (jsonDecode(res.body) as Map<String, dynamic>?) ?? <String, dynamic>{};
    if (res.statusCode < 200 || res.statusCode >= 300) {
      final detail = decoded['detail'];
      throw ApiException(detail is String ? detail : '请求失败 (${res.statusCode})');
    }
    return decoded;
  }

  Future<List<Todo>> listTodos({String? status}) async {
    final data = await _send('GET', '/todos',
        query: status != null ? {'status': status} : null);
    return (data['todos'] as List)
        .map((e) => Todo.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final data = await _send('POST', '/todos', body: {
      'title': title,
      if (dueAt != null) 'due_at': dueAt,
      if (category != null) 'category': category,
    });
    return Todo.fromJson(data);
  }

  Future<void> completeTodo(int id) => _send('POST', '/todos/$id/complete');
  Future<void> deleteTodo(int id) => _send('DELETE', '/todos/$id');

  Future<List<Note>> listNotes() async {
    final data = await _send('GET', '/notes');
    return (data['notes'] as List)
        .map((e) => Note.fromListJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<Note>> searchNotes(String query, {int topK = 5}) async {
    final data = await _send('GET', '/notes/search', query: {'q': query, 'top_k': '$topK'});
    return (data['hits'] as List)
        .map((e) => Note.fromSearchJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> deleteNote(int id) => _send('DELETE', '/notes/$id');
  Future<void> createNote(String content) => _send('POST', '/notes', body: {'content': content});
}
```

`app/lib/services/chat_service.dart`：在文件顶部（`parseSseLine` 之前）加 `import 'dart:io';`，文件末尾追加：

```dart
class ChatService {
  ChatService({required this.baseUrl});

  String baseUrl;

  Stream<ChatEvent> stream(String message, String? sessionId) async* {
    final client = HttpClient();
    try {
      final req = await client.postUrl(Uri.parse('$baseUrl/api/chat'));
      req.headers.contentType = ContentType.json;
      req.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
      req.write(jsonEncode({'message': message, 'session_id': sessionId}));
      final res = await req.close();
      if (res.statusCode != 200) {
        final body = await utf8.decoder.bind(res).join();
        var detail = '服务器错误 (${res.statusCode})';
        try {
          final decoded = jsonDecode(body) as Map<String, dynamic>;
          if (decoded['detail'] is String) detail = decoded['detail'] as String;
        } on FormatException {
          // ignore: keep default detail
        }
        yield ErrorEvent(detail);
        return;
      }
      final lines = res.transform(utf8.decoder).transform(const LineSplitter());
      await for (final line in lines) {
        final ev = parseSseLine(line);
        if (ev != null) yield ev;
      }
    } on SocketException catch (e) {
      yield ErrorEvent('无法连接服务器: ${e.message}');
    } on HttpException catch (e) {
      yield ErrorEvent('请求失败: ${e.message}');
    } finally {
      client.close(force: true);
    }
  }
}
```

`chat_service.dart` 顶部 import 顺序（三段）应为：

```dart
import 'dart:convert';
import 'dart:io';
```

（`parseSseLine` 用到 `dart:convert`；`ChatService` 用到 `dart:io`。）

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/settings_service_test.dart test/api_client_test.dart`
Expected: 全过（8 个）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/services app/test
git commit -m "feat: add settings, api client, and SSE chat services"
```

---

### Task 6: App 状态层 —— 三个 controller + 单元测试

**Files:**
- Create: `app/lib/state/chat_controller.dart`、`app/lib/state/todos_controller.dart`、`app/lib/state/notes_controller.dart`
- Test: `app/test/controllers_test.dart`

**Interfaces:**
- Consumes: Task 5 的 `ApiClient`/`ChatService`/`ChatEvent` 系列、`ApiException`；Task 4 的 `ChatBubble`/`BubbleKind`、`Todo`/`Note`
- Produces: `ChatController`、`TodosController`、`NotesController`（ChangeNotifier，Task 7-11 的页面消费）。`TodosController`/`NotesController` 的 `remove` 是**乐观删除**（先从列表移除再调 API），保证 Dismissible 不触发 assert。

- [ ] **Step 1: 写失败测试**

`app/test/controllers_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/chat_message.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/models/todo.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:personal_ai_app/state/todos_controller.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Todo> todos = [];
  final List<Note> notes = [];
  final List<String> noteContents = [];
  bool failLoad = false;

  @override
  Future<List<Todo>> listTodos({String? status}) async {
    if (failLoad) throw ApiException('服务器不可用');
    return List.of(todos);
  }

  @override
  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final t = Todo(id: todos.length + 1, title: title);
    todos.add(t);
    return t;
  }

  @override
  Future<void> completeTodo(int id) async {
    final i = todos.indexWhere((t) => t.id == id);
    todos[i] = Todo(id: id, title: todos[i].title, status: 'done');
  }

  @override
  Future<void> deleteTodo(int id) async {
    todos.removeWhere((t) => t.id == id);
  }

  @override
  Future<List<Note>> listNotes() async => List.of(notes);

  @override
  Future<List<Note>> searchNotes(String query, {int topK = 5}) async =>
      notes.where((n) => n.content.contains(query)).toList();

  @override
  Future<void> deleteNote(int id) async {
    notes.removeWhere((n) => n.id == id);
  }

  @override
  Future<void> createNote(String content) async {
    noteContents.add(content);
  }
}

class FakeChatService extends ChatService {
  FakeChatService(this._events) : super(baseUrl: 'http://test');

  final List<ChatEvent> _events;
  String? lastMessage;
  String? lastSession;

  @override
  Stream<ChatEvent> stream(String message, String? sessionId) async* {
    lastMessage = message;
    lastSession = sessionId;
    yield* Stream.fromIterable(_events);
  }
}

void main() {
  test('TodosController 加载与错误态', () async {
    final api = FakeApiClient();
    final c = TodosController(apiClient: api);
    await c.load();
    expect(c.todos, isEmpty);
    expect(c.error, isNull);

    api.failLoad = true;
    await c.load();
    expect(c.error, isNotNull);
  });

  test('TodosController 完成与删除', () async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await c.complete(c.todos.single);
    expect(c.todos.single.isDone, isTrue);
    await c.remove(c.todos.single);
    expect(c.todos, isEmpty);
  });

  test('ChatController 把事件流组装成气泡', () async {
    final api = FakeApiClient();
    final service = FakeChatService([
      SessionEvent('sid-1'),
      TokenEvent('你'),
      TokenEvent('好'),
      ToolEvent(name: 'now', arguments: const {}, result: const {'datetime': '2026-08-04'}),
      DoneEvent(),
    ]);
    final c = ChatController(chatService: service, apiClient: api);
    await c.send('现在几点');
    expect(service.lastMessage, '现在几点');
    expect(service.lastSession, isNull);
    expect(c.sessionId, 'sid-1');
    expect(c.bubbles[1].content, '你好');
    expect(c.bubbles.any((b) => b.kind == BubbleKind.tool && b.name == 'now'), isTrue);
    expect(c.streaming, isFalse);
  });

  test('ChatController 错误事件变错误气泡', () async {
    final api = FakeApiClient();
    final c = ChatController(
      chatService: FakeChatService([ErrorEvent('无法连接服务器')]),
      apiClient: api,
    );
    await c.send('hi');
    expect(c.bubbles.last.kind, BubbleKind.error);
  });

  test('ChatController 记录笔记', () async {
    final api = FakeApiClient();
    final c = ChatController(chatService: FakeChatService([]), apiClient: api);
    await c.saveNote('买咖啡豆');
    expect(api.noteContents, ['买咖啡豆']);
  });

  test('NotesController 搜索与清空', () async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '明天下班买咖啡豆'));
    api.notes.add(Note(id: 2, content: '开会记录'));
    final c = NotesController(apiClient: api);
    await c.load();
    expect(c.notes.length, 2);
    await c.search('咖啡');
    expect(c.notes.single.id, 1);
    await c.search('');
    expect(c.notes.length, 2);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/controllers_test.dart`
Expected: FAIL——controller 类未定义。

- [ ] **Step 3: 实现最小代码**

`app/lib/state/todos_controller.dart`：

```dart
import 'package:flutter/foundation.dart';

import '../models/todo.dart';
import '../services/api_client.dart';

class TodosController extends ChangeNotifier {
  TodosController({required this.apiClient});

  final ApiClient apiClient;

  List<Todo> todos = [];
  bool loading = false;
  String? error;

  Future<void> load() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      todos = await apiClient.listTodos();
    } catch (e) {
      error = '加载失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> create(String title) async {
    await apiClient.createTodo(title: title);
    await load();
  }

  Future<void> complete(Todo todo) async {
    await apiClient.completeTodo(todo.id);
    await load();
  }

  Future<void> remove(Todo todo) async {
    todos.removeWhere((t) => t.id == todo.id);
    notifyListeners();
    try {
      await apiClient.deleteTodo(todo.id);
    } catch (_) {
      error = '删除失败';
      notifyListeners();
    }
    await load();
  }
}
```

`app/lib/state/notes_controller.dart`：

```dart
import 'package:flutter/foundation.dart';

import '../models/note.dart';
import '../services/api_client.dart';

class NotesController extends ChangeNotifier {
  NotesController({required this.apiClient});

  final ApiClient apiClient;

  List<Note> notes = [];
  bool loading = false;
  bool searching = false;
  String? error;

  Future<void> load() async {
    loading = true;
    searching = false;
    error = null;
    notifyListeners();
    try {
      notes = await apiClient.listNotes();
    } catch (e) {
      error = '加载失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> search(String query) async {
    final q = query.trim();
    loading = true;
    searching = q.isNotEmpty;
    error = null;
    notifyListeners();
    try {
      notes = q.isEmpty ? await apiClient.listNotes() : await apiClient.searchNotes(q);
    } catch (e) {
      error = '搜索失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> remove(Note note) async {
    notes.removeWhere((n) => n.id == note.id);
    notifyListeners();
    try {
      await apiClient.deleteNote(note.id);
    } catch (_) {
      error = '删除失败';
      notifyListeners();
    }
    await load();
  }
}
```

`app/lib/state/chat_controller.dart`：

```dart
import 'package:flutter/foundation.dart';

import '../models/chat_message.dart';
import '../services/api_client.dart';
import '../services/chat_service.dart';

class ChatController extends ChangeNotifier {
  ChatController({required this.chatService, required this.apiClient});

  final ChatService chatService;
  final ApiClient apiClient;

  final List<ChatBubble> bubbles = [];
  String? sessionId;
  bool streaming = false;

  Future<void> send(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || streaming) return;
    bubbles.add(ChatBubble(kind: BubbleKind.user, content: trimmed));
    final assistant = ChatBubble(kind: BubbleKind.assistant);
    bubbles.add(assistant);
    streaming = true;
    notifyListeners();
    try {
      await for (final ev in chatService.stream(trimmed, sessionId)) {
        switch (ev) {
          case SessionEvent(:final sessionId):
            this.sessionId = sessionId;
          case TokenEvent(:final content):
            assistant.content += content;
            notifyListeners();
          case ToolEvent(:final name, :final arguments, :final result):
            bubbles.add(ChatBubble(kind: BubbleKind.tool, name: name, arguments: arguments, result: result));
            notifyListeners();
          case ErrorEvent(:final message):
            bubbles.add(ChatBubble(kind: BubbleKind.error, content: message));
            notifyListeners();
          case DoneEvent():
            break;
        }
      }
    } finally {
      streaming = false;
      notifyListeners();
    }
  }

  Future<void> saveNote(String content) async {
    final trimmed = content.trim();
    if (trimmed.isEmpty) return;
    await apiClient.createNote(trimmed);
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/controllers_test.dart`
Expected: 全过（7 个）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/state app/test
git commit -m "feat: add chat/todos/notes controllers"
```

---

### Task 7: 页面骨架 —— home_shell + settings_screen + widget 测试

**Files:**
- Create: `app/lib/home_shell.dart`、`app/lib/screens/settings_screen.dart`
- Test: `app/test/home_shell_test.dart`、`app/test/settings_screen_test.dart`

**Interfaces:**
- Consumes: Task 5 的 `SettingsService`/`ApiClient`/`ChatService`；Task 6 的三个 controller；Task 8-10 的 `ChatScreen`/`TodosScreen`/`NotesScreen`（本 Task 先引用，Task 8-10 才创建文件）
- Produces: `HomeShell`（底部导航 + 设置入口）、`SettingsScreen`（改服务器地址，保存时同步更新 `ApiClient.baseUrl`/`ChatService.baseUrl`）。`main.dart` 装配在 Task 11。

- [ ] **Step 1: 写失败测试**

`app/test/settings_screen_test.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/screens/settings_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget wrap(SettingsService settings, ApiClient api, ChatService chat) => MultiProvider(
      providers: [
        Provider.value(value: settings),
        Provider.value(value: api),
        Provider.value(value: chat),
      ],
      child: const MaterialApp(home: SettingsScreen()),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('保存后更新 settings 与各 client 的 baseUrl', (tester) async {
    final settings = SettingsService();
    await settings.load();
    final api = ApiClient(baseUrl: settings.serverUrl);
    final chat = ChatService(baseUrl: settings.serverUrl);
    await tester.pumpWidget(wrap(settings, api, chat));

    await tester.enterText(find.byType(TextField), 'http://192.168.1.10:8000');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(settings.serverUrl, 'http://192.168.1.10:8000');
    expect(api.baseUrl, 'http://192.168.1.10:8000');
    expect(chat.baseUrl, 'http://192.168.1.10:8000');
  });
}
```

`app/test/home_shell_test.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/home_shell.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:personal_ai_app/state/todos_controller.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget wrap() {
  final settings = SettingsService()..serverUrl = 'http://test';
  final api = ApiClient(baseUrl: 'http://test');
  final chat = ChatService(baseUrl: 'http://test');
  return MultiProvider(
    providers: [
      Provider.value(value: settings),
      Provider.value(value: api),
      Provider.value(value: chat),
      ChangeNotifierProvider(create: (_) => ChatController(chatService: chat, apiClient: api)),
      ChangeNotifierProvider(create: (_) => TodosController(apiClient: api)),
      ChangeNotifierProvider(create: (_) => NotesController(apiClient: api)),
    ],
    child: const MaterialApp(home: HomeShell()),
  );
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('底部导航切换聊天/待办/笔记', (tester) async {
    await tester.pumpWidget(wrap());
    expect(find.text('有什么可以帮你？'), findsOneWidget);

    await tester.tap(find.text('待办'));
    await tester.pumpAndSettle();
    expect(find.text('暂无待办'), findsOneWidget);

    await tester.tap(find.text('笔记'));
    await tester.pumpAndSettle();
    expect(find.text('暂无笔记'), findsOneWidget);
  });
}
```

注意：home_shell_test 引用 `ChatScreen`/`TodosScreen`/`NotesScreen`（Task 8-10 才存在）。为了让本 Task 的测试能编译，三个 screen 文件本 Task 先用**占位实现**（Task 8-10 逐个替换成真实现）：

- `app/lib/screens/chat_screen.dart`：

```dart
import 'package:flutter/material.dart';

class ChatScreen extends StatelessWidget {
  const ChatScreen({super.key});

  @override
  Widget build(BuildContext context) => const Center(child: Text('有什么可以帮你？'));
}
```

- `app/lib/screens/todos_screen.dart`：

```dart
import 'package:flutter/material.dart';

class TodosScreen extends StatelessWidget {
  const TodosScreen({super.key});

  @override
  Widget build(BuildContext context) => const Center(child: Text('暂无待办'));
}
```

- `app/lib/screens/notes_screen.dart`：

```dart
import 'package:flutter/material.dart';

class NotesScreen extends StatelessWidget {
  const NotesScreen({super.key});

  @override
  Widget build(BuildContext context) => const Center(child: Text('暂无笔记'));
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/settings_screen_test.dart test/home_shell_test.dart`
Expected: FAIL——`home_shell.dart`/`settings_screen.dart`/三个 screen 未定义。

- [ ] **Step 3: 实现最小代码**

`app/lib/home_shell.dart`：

```dart
import 'package:flutter/material.dart';

import 'screens/chat_screen.dart';
import 'screens/notes_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/todos_screen.dart';

class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Personal AI'),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            tooltip: '设置',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
      body: switch (_index) {
        0 => const ChatScreen(),
        1 => const TodosScreen(),
        _ => const NotesScreen(),
      },
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.chat_bubble_outline), selectedIcon: Icon(Icons.chat_bubble), label: '聊天'),
          NavigationDestination(icon: Icon(Icons.checklist_outlined), selectedIcon: Icon(Icons.checklist), label: '待办'),
          NavigationDestination(icon: Icon(Icons.note_alt_outlined), selectedIcon: Icon(Icons.note_alt), label: '笔记'),
        ],
      ),
    );
  }
}
```

`app/lib/screens/settings_screen.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/chat_service.dart';
import '../services/settings_service.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _controller;
  late final SettingsService _settings;
  late final ApiClient _api;
  late final ChatService _chat;

  @override
  void initState() {
    super.initState();
    _settings = context.read<SettingsService>();
    _api = context.read<ApiClient>();
    _chat = context.read<ChatService>();
    _controller = TextEditingController(text: _settings.serverUrl);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final url = _controller.text.trim();
    if (url.isEmpty || !url.startsWith('http')) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入以 http 开头的服务器地址')),
      );
      return;
    }
    await _settings.setServerUrl(url);
    _api.baseUrl = url;
    _chat.baseUrl = url;
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已保存服务器地址')),
      );
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextField(
              controller: _controller,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                labelText: '服务器地址',
                hintText: 'http://电脑IP:8000',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              child: FilledButton(onPressed: _save, child: const Text('保存')),
            ),
            const SizedBox(height: 8),
            Text(
              '默认 ${SettingsService.defaultServerUrl}（安卓模拟器）。真机请填电脑的局域网 IP，例如 http://192.168.1.10:8000',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/settings_screen_test.dart test/home_shell_test.dart`
Expected: 全过（2 个 widget 测试）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/home_shell.dart app/lib/screens app/test
git commit -m "feat: add home shell and settings screen"
```

---

### Task 8: 聊天页 chat_screen + widget 测试

**Files:**
- Modify: `app/lib/screens/chat_screen.dart`（占位实现替换为真实现）
- Test: `app/test/chat_screen_test.dart`

**Interfaces:**
- Consumes: Task 6 的 `ChatController`（`bubbles`/`sessionId`/`streaming`/`send`/`saveNote`）；Task 4 的 `ChatBubble`/`BubbleKind`
- Produces: 真 `ChatScreen`（消息列表 + 输入框 + 记笔记按钮 + 发送按钮，reverse ListView 自动贴底）

- [ ] **Step 1: 写失败测试**

`app/test/chat_screen_test.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/screens/chat_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/state/chat_controller.dart';
import 'package:provider/provider.dart';

class FakeChatService extends ChatService {
  FakeChatService(this._events) : super(baseUrl: 'http://test');

  final List<ChatEvent> _events;

  @override
  Stream<ChatEvent> stream(String message, String? sessionId) => Stream.fromIterable(_events);
}

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<String> notes = [];

  @override
  Future<void> createNote(String content) async => notes.add(content);
}

Widget wrap(ChatController controller) => ChangeNotifierProvider.value(
      value: controller,
      child: const MaterialApp(home: Scaffold(body: ChatScreen())),
    );

void main() {
  testWidgets('发送后展示用户气泡、AI 气泡与工具卡片', (tester) async {
    final api = FakeApiClient();
    final controller = ChatController(
      chatService: FakeChatService([
        SessionEvent('sid-1'),
        TokenEvent('现在'),
        TokenEvent('是 12:00'),
        ToolEvent(name: 'now', arguments: const {}, result: const {'datetime': '2026-08-04T12:00:00'}),
        DoneEvent(),
      ]),
      apiClient: api,
    );
    await tester.pumpWidget(wrap(controller));

    await tester.enterText(find.byType(TextField), '现在几点');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    expect(find.text('现在几点'), findsOneWidget);
    expect(find.textContaining('现在是 12:00'), findsOneWidget);
    expect(find.textContaining('工具调用'), findsOneWidget);
    expect(find.textContaining('now'), findsOneWidget);
  });

  testWidgets('记笔记按钮把输入写入后端并提示', (tester) async {
    final api = FakeApiClient();
    final controller = ChatController(chatService: FakeChatService([]), apiClient: api);
    await tester.pumpWidget(wrap(controller));

    await tester.enterText(find.byType(TextField), '买咖啡豆');
    await tester.tap(find.byIcon(Icons.note_add_outlined));
    await tester.pumpAndSettle();

    expect(api.notes, ['买咖啡豆']);
    expect(find.text('已记录到笔记'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/chat_screen_test.dart`
Expected: FAIL——ChatScreen 目前是占位（`find.byType(TextField)` 找不到，且无 send 图标）。

- [ ] **Step 3: 实现最小代码**

把 `app/lib/screens/chat_screen.dart` 整体替换为：

```dart
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/chat_message.dart';
import '../state/chat_controller.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text;
    if (text.trim().isEmpty) return;
    _input.clear();
    await context.read<ChatController>().send(text);
  }

  Future<void> _note() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ChatController>().saveNote(text);
      _input.clear();
      messenger.showSnackBar(const SnackBar(content: Text('已记录到笔记')));
    } catch (_) {
      messenger.showSnackBar(const SnackBar(content: Text('记录失败，请检查服务器地址')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ChatController>();
    final bubbles = controller.bubbles.reversed.toList();
    return Column(
      children: [
        Expanded(
          child: bubbles.isEmpty
              ? const Center(child: Text('有什么可以帮你？', style: TextStyle(color: Colors.grey)))
              : ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.all(12),
                  itemCount: bubbles.length,
                  itemBuilder: (_, i) => _BubbleView(bubble: bubbles[i]),
                ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _input,
                    minLines: 1,
                    maxLines: 4,
                    decoration: const InputDecoration(
                      hintText: '输入消息，或记成笔记…',
                      border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(20))),
                      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    ),
                    onSubmitted: (_) => _send(),
                  ),
                ),
                IconButton(
                  tooltip: '把当前输入记成笔记',
                  icon: const Icon(Icons.note_add_outlined),
                  onPressed: _note,
                ),
                IconButton.filled(
                  tooltip: '发送',
                  icon: const Icon(Icons.send),
                  onPressed: _send,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _BubbleView extends StatelessWidget {
  const _BubbleView({required this.bubble});

  final ChatBubble bubble;

  @override
  Widget build(BuildContext context) {
    switch (bubble.kind) {
      case BubbleKind.user:
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primary,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content, style: const TextStyle(color: Colors.white)),
          ),
        );
      case BubbleKind.assistant:
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content),
          ),
        );
      case BubbleKind.tool:
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Colors.grey.shade100,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('工具调用: ${bubble.name}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 4),
              Text(_pretty(bubble.arguments)),
              if (bubble.result != null && bubble.result!.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(_pretty(bubble.result)),
              ],
            ],
          ),
        );
      case BubbleKind.error:
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.errorContainer,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content),
          ),
        );
    }
  }

  String _pretty(Map<String, dynamic>? m) {
    if (m == null || m.isEmpty) return '';
    return JsonEncoder.withIndent('  ').convert(m);
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/chat_screen_test.dart`
Expected: 全过（2 个 widget 测试）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/screens/chat_screen.dart app/test/chat_screen_test.dart
git commit -m "feat: build chat screen with SSE streaming and tool cards"
```

---

### Task 9: 待办页 todos_screen + widget 测试

**Files:**
- Modify: `app/lib/screens/todos_screen.dart`（占位替换为真实现）
- Test: `app/test/todos_screen_test.dart`

**Interfaces:**
- Consumes: Task 6 的 `TodosController`（`todos`/`loading`/`error`/`load`/`create`/`complete`/`remove`）；Task 4 的 `Todo`
- Produces: 真 `TodosScreen`（列表 + 新建对话框 + 完成 checkbox + 滑动删除 + 下拉刷新 + 空态/错误态 + FAB）

- [ ] **Step 1: 写失败测试**

`app/test/todos_screen_test.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/todo.dart';
import 'package:personal_ai_app/screens/todos_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/state/todos_controller.dart';
import 'package:provider/provider.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Todo> todos = [];
  final List<int> completed = [];
  final List<int> deleted = [];

  @override
  Future<List<Todo>> listTodos({String? status}) async => List.of(todos);

  @override
  Future<Todo> createTodo({required String title, String? dueAt, String? category}) async {
    final t = Todo(id: todos.length + 1, title: title);
    todos.insert(0, t);
    return t;
  }

  @override
  Future<void> completeTodo(int id) async {
    completed.add(id);
    final i = todos.indexWhere((t) => t.id == id);
    todos[i] = Todo(id: id, title: todos[i].title, status: 'done');
  }

  @override
  Future<void> deleteTodo(int id) async {
    deleted.add(id);
    todos.removeWhere((t) => t.id == id);
  }
}

Widget wrap(TodosController c) =>
    ChangeNotifierProvider.value(value: c, child: const MaterialApp(home: TodosScreen()));

void main() {
  testWidgets('展示待办并可完成', (tester) async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    expect(find.text('买牛奶'), findsOneWidget);
    await tester.tap(find.byType(Checkbox));
    await tester.pumpAndSettle();
    expect(api.completed, [1]);
  });

  testWidgets('滑动删除待办', (tester) async {
    final api = FakeApiClient();
    api.todos.add(Todo(id: 1, title: '买牛奶'));
    final c = TodosController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    await tester.drag(find.text('买牛奶'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(api.deleted, [1]);
    expect(find.text('买牛奶'), findsNothing);
  });

  testWidgets('空态展示', (tester) async {
    final c = TodosController(apiClient: FakeApiClient());
    await tester.pumpWidget(wrap(c));
    expect(find.text('暂无待办'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/todos_screen_test.dart`
Expected: FAIL——TodosScreen 是占位（`find.byType(Checkbox)` 不存在）。

- [ ] **Step 3: 实现最小代码**

把 `app/lib/screens/todos_screen.dart` 整体替换为：

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/todo.dart';
import '../state/todos_controller.dart';

class TodosScreen extends StatefulWidget {
  const TodosScreen({super.key});

  @override
  State<TodosScreen> createState() => _TodosScreenState();
}

class _TodosScreenState extends State<TodosScreen> {
  Future<void> _add() async {
    final controller = context.read<TodosController>();
    final titleController = TextEditingController();
    final saved = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建待办'),
        content: TextField(
          controller: titleController,
          autofocus: true,
          decoration: const InputDecoration(hintText: '待办内容'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.of(ctx).pop(false), child: const Text('取消')),
          FilledButton(
            onPressed: () {
              if (titleController.text.trim().isEmpty) return;
              Navigator.of(ctx).pop(true);
            },
            child: const Text('确定'),
          ),
        ],
      ),
    );
    final title = titleController.text.trim();
    titleController.dispose();
    if (saved == true && title.isNotEmpty) {
      await controller.create(title);
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<TodosController>();
    final Widget body;
    if (controller.loading) {
      body = const Center(child: CircularProgressIndicator());
    } else if (controller.error != null) {
      body = Center(child: Text(controller.error!));
    } else if (controller.todos.isEmpty) {
      body = const Center(child: Text('暂无待办'));
    } else {
      body = RefreshIndicator(
        onRefresh: controller.load,
        child: ListView.builder(
          itemCount: controller.todos.length,
          itemBuilder: (_, i) {
            final todo = controller.todos[i];
            return Dismissible(
              key: ValueKey('todo-${todo.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                color: Colors.red,
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                child: const Icon(Icons.delete, color: Colors.white),
              ),
              onDismissed: (_) => controller.remove(todo),
              child: ListTile(
                leading: Checkbox(
                  value: todo.isDone,
                  onChanged: (_) => controller.complete(todo),
                ),
                title: Text(
                  todo.title,
                  style: todo.isDone
                      ? const TextStyle(decoration: TextDecoration.lineThrough)
                      : null,
                ),
                subtitle: [todo.category, todo.dueAt].whereType<String>().isEmpty
                    ? null
                    : Text([todo.category, todo.dueAt].whereType<String>().join(' · ')),
              ),
            );
          },
        ),
      );
    }
    return Scaffold(
      body: body,
      floatingActionButton: FloatingActionButton(
        onPressed: _add,
        tooltip: '新建待办',
        child: const Icon(Icons.add),
      ),
    );
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/todos_screen_test.dart`
Expected: 全过（3 个 widget 测试）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/screens/todos_screen.dart app/test/todos_screen_test.dart
git commit -m "feat: build todos screen with full CRUD"
```

---

### Task 10: 笔记页 notes_screen + widget 测试

**Files:**
- Modify: `app/lib/screens/notes_screen.dart`（占位替换为真实现）
- Test: `app/test/notes_screen_test.dart`

**Interfaces:**
- Consumes: Task 6 的 `NotesController`（`notes`/`loading`/`searching`/`error`/`load`/`search`/`remove`）；Task 4 的 `Note`
- Produces: 真 `NotesScreen`（顶部搜索框 + 列表 + 滑动删除 + 下拉刷新 + 空态/错误态）

- [ ] **Step 1: 写失败测试**

`app/test/notes_screen_test.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/models/note.dart';
import 'package:personal_ai_app/screens/notes_screen.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/state/notes_controller.dart';
import 'package:provider/provider.dart';

class FakeApiClient extends ApiClient {
  FakeApiClient() : super(baseUrl: 'http://test');

  final List<Note> notes = [];
  final List<int> deleted = [];
  String? lastQuery;

  @override
  Future<List<Note>> listNotes() async => List.of(notes);

  @override
  Future<List<Note>> searchNotes(String query, {int topK = 5}) async {
    lastQuery = query;
    return notes.where((n) => n.content.contains(query)).toList();
  }

  @override
  Future<void> deleteNote(int id) async {
    deleted.add(id);
    notes.removeWhere((n) => n.id == id);
  }
}

Widget wrap(NotesController c) =>
    ChangeNotifierProvider.value(value: c, child: const MaterialApp(home: Scaffold(body: NotesScreen())));

void main() {
  testWidgets('展示笔记并搜索过滤', (tester) async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '明天下班买咖啡豆'));
    api.notes.add(Note(id: 2, content: '开会记录'));
    final c = NotesController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    expect(find.textContaining('买咖啡豆'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '咖啡');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();
    expect(api.lastQuery, '咖啡');
    expect(find.textContaining('买咖啡豆'), findsOneWidget);
    expect(find.textContaining('开会记录'), findsNothing);
  });

  testWidgets('滑动删除笔记', (tester) async {
    final api = FakeApiClient();
    api.notes.add(Note(id: 1, content: '买咖啡豆'));
    final c = NotesController(apiClient: api);
    await c.load();
    await tester.pumpWidget(wrap(c));
    await tester.pump();

    await tester.drag(find.textContaining('买咖啡豆'), const Offset(-500, 0));
    await tester.pumpAndSettle();
    expect(api.deleted, [1]);
    expect(find.textContaining('买咖啡豆'), findsNothing);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/notes_screen_test.dart`
Expected: FAIL——NotesScreen 是占位。

- [ ] **Step 3: 实现最小代码**

把 `app/lib/screens/notes_screen.dart` 整体替换为：

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/notes_controller.dart';

class NotesScreen extends StatefulWidget {
  const NotesScreen({super.key});

  @override
  State<NotesScreen> createState() => _NotesScreenState();
}

class _NotesScreenState extends State<NotesScreen> {
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _submitSearch() async {
    await context.read<NotesController>().search(_search.text);
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<NotesController>();
    final Widget list;
    if (controller.loading) {
      list = const Center(child: CircularProgressIndicator());
    } else if (controller.error != null) {
      list = Center(child: Text(controller.error!));
    } else if (controller.notes.isEmpty) {
      list = Center(child: Text(controller.searching ? '没有搜到相关笔记' : '暂无笔记'));
    } else {
      list = RefreshIndicator(
        onRefresh: controller.load,
        child: ListView.builder(
          itemCount: controller.notes.length,
          itemBuilder: (_, i) {
            final note = controller.notes[i];
            return Dismissible(
              key: ValueKey('note-${note.id}'),
              direction: DismissDirection.endToStart,
              background: Container(
                color: Colors.red,
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 20),
                child: const Icon(Icons.delete, color: Colors.white),
              ),
              onDismissed: (_) => controller.remove(note),
              child: ListTile(
                leading: const Icon(Icons.note_outlined),
                title: Text(note.content, maxLines: 3, overflow: TextOverflow.ellipsis),
                subtitle: note.score != null
                    ? Text('相关度 ${note.score!.toStringAsFixed(2)}')
                    : null,
              ),
            );
          },
        ),
      );
    }
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _search,
            decoration: InputDecoration(
              hintText: '搜索笔记（语义检索）',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: controller.searching
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _search.clear();
                        controller.search('');
                      },
                    ),
              border: const OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(20))),
              isDense: true,
            ),
            onSubmitted: (_) => _submitSearch(),
          ),
        ),
        Expanded(child: list),
      ],
    );
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/notes_screen_test.dart`
Expected: 全过（2 个 widget 测试）。

- [ ] **Step 5: analyze + 提交**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter analyze`
Expected: 无 issue。

```bash
git add app/lib/screens/notes_screen.dart app/test/notes_screen_test.dart
git commit -m "feat: build notes screen with semantic search and delete"
```

---

### Task 11: 集成收尾 —— main.dart 装配 + 全量校验 + 真机指引

**Files:**
- Create: `app/lib/main.dart`
- Modify: `app/test/widget_test.dart`（脚手架 smoke test 换成 App 启动 smoke test）

**Interfaces:**
- Consumes: Task 5 的 `SettingsService`/`ApiClient`/`ChatService`；Task 6 的三个 controller；Task 7 的 `HomeShell`
- Produces: `PersonalAiApp`（可运行 App）；最终全量测试/静态检查绿；真机手动验证清单

- [ ] **Step 1: 写失败测试**

把 `app/test/widget_test.dart` 替换为：

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/main.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('App 启动后显示聊天页', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsService()..serverUrl = 'http://test';
    final api = ApiClient(baseUrl: 'http://test');
    final chat = ChatService(baseUrl: 'http://test');
    await tester.pumpWidget(
      PersonalAiApp(settings: settings, apiClient: api, chatService: chat),
    );
    await tester.pump();
    expect(find.text('有什么可以帮你？'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/widget_test.dart`
Expected: FAIL——`main.dart` 没有 `PersonalAiApp`（编译错误）。

- [ ] **Step 3: 实现最小代码**

`app/lib/main.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'home_shell.dart';
import 'services/api_client.dart';
import 'services/chat_service.dart';
import 'services/settings_service.dart';
import 'state/chat_controller.dart';
import 'state/notes_controller.dart';
import 'state/todos_controller.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = SettingsService();
  await settings.load();
  final apiClient = ApiClient(baseUrl: settings.serverUrl);
  final chatService = ChatService(baseUrl: settings.serverUrl);
  runApp(PersonalAiApp(settings: settings, apiClient: apiClient, chatService: chatService));
}

class PersonalAiApp extends StatelessWidget {
  const PersonalAiApp({
    super.key,
    required this.settings,
    required this.apiClient,
    required this.chatService,
  });

  final SettingsService settings;
  final ApiClient apiClient;
  final ChatService chatService;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider.value(value: settings),
        Provider.value(value: apiClient),
        Provider.value(value: chatService),
        ChangeNotifierProvider(
          create: (_) => ChatController(chatService: chatService, apiClient: apiClient),
        ),
        ChangeNotifierProvider(create: (_) => TodosController(apiClient: apiClient)..load()),
        ChangeNotifierProvider(create: (_) => NotesController(apiClient: apiClient)..load()),
      ],
      child: MaterialApp(
        title: 'Personal AI',
        theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
        home: const HomeShell(),
      ),
    );
  }
}
```

- [ ] **Step 4: 运行确认通过**

Run: `cd app && /c/Users/gry/program/flutter/bin/flutter test test/widget_test.dart`
Expected: 1 passed。

- [ ] **Step 5: App 全量校验**

Run:

```bash
cd /c/Users/gry/program/personal_ai/app
export FLUTTER_SUPPRESS_ANALYTICS=true
/c/Users/gry/program/flutter/bin/flutter test
/c/Users/gry/program/flutter/bin/flutter analyze
```

Expected: 所有 app 测试通过（Task 4-11 累计 20+ 个）；analyze 无 issue。

- [ ] **Step 6: 后端全量回归**

Run: `cd /c/Users/gry/program/personal_ai && .venv/Scripts/python -m pytest -q`
Expected: 全部通过（100 个）。

- [ ] **Step 7: 提交**

```bash
git add app/lib/main.dart app/test/widget_test.dart
git commit -m "feat: wire up app entry with providers and full verification"
```

- [ ] **Step 8: 记录真机手动验证清单**（写入本 Task 的报告文件，不创建新文档）

真机验证步骤（用户在有 Android SDK/Java 的机器上执行，或后续装好 Android SDK 后）：
1. 电脑与小米手机连同一 Wi-Fi；电脑 `ipconfig` 查局域网 IP。
2. `flutter build apk --release` 打包（需 Android SDK + JDK），安装到手机。
3. 打开 App → 右上角设置 → 填 `http://<电脑IP>:8000` → 保存。
4. 聊天：发消息看流式回复；问"现在几点"看 `now` 工具卡片；"记下：明天下班买咖啡豆" 看工具调用 + 笔记写入。
5. 记笔记按钮：输入内容 → 点"记成笔记"图标 → 提示"已记录到笔记"。
6. 待办页：新建/完成/滑动删除；下拉刷新。
7. 笔记页：列表展示；搜索"咖啡"看语义检索；滑动删除。
8. 同一会话内追问"我刚才记了什么"验证会话恢复。

---

## Self-Review

**1. Spec 覆盖**（对照 `docs/superpowers/specs/2026-08-04-phase4-android-app-design.md`）：
- §3 REST 契约 → Task 1 + Task 2（7 个端点全在）。✓
- §4 App 结构（3 页面 + 设置 + 服务层 + 状态层 + 3 依赖）→ Task 3-11。✓
- §5 数据流（SSE 逐行解析、工具卡片、记笔记按钮、待办/笔记 CRUD、设置页改地址全局生效）→ Task 4/5/6/8/9/10/11。✓
- §6 错误处理（错误态 + 重试、Snackbar detail、空态、cleartext、地址校验）→ Task 5/8/9/10（错误态在 controller + 页面）、Task 3（cleartext）、Task 7（地址校验）。✓
- §7 配置与工具链（默认地址、设置页持久化、Task 0 工具链）→ Task 3（SDK 装到固定路径）、Task 5（SettingsService）、Task 7（设置页）。✓
- §8 测试（后端 FakeConn + 端点测试、SSE 解析单测、mock widget 测试、真机清单）→ Task 1/2/4/5/6/7/8/9/10/11。✓
- §9 不做项 → Global Constraints 已锁定（无登录/无外网/无第三方 SSE 包/无重型状态管理）。✓

**2. 占位符扫描**：无 TBD/TODO/"类似 Task N"。每步有真实代码。Task 7 引入的 3 个 screen 占位是**临时脚手架**，随后 Task 8/9/10 逐一把占位整体替换，属正常渐进实现，不是计划占位。✓

**3. 类型/签名一致性**：
- `parseSseLine(String) → ChatEvent?`（Task 4 定义，Task 5 的 ChatService 调用，Task 4 测试断言）一致。✓
- `ApiClient` 方法签名（listTodos/createTodo/completeTodo/deleteTodo/listNotes/searchNotes/deleteNote/createNote + baseUrl + client 可选参数）在 Task 5 定义，Task 5/6/9/10 的 Fake 全部 `implements`/`extends` 覆盖一致。✓
- controller 字段/方法（TodosController.todos/loading/error/load/create/complete/remove；NotesController.notes/searching/search/remove；ChatController.bubbles/sessionId/streaming/send/saveNote）在 Task 6 定义，Task 7/8/9/10/11 引用一致。✓
- 后端端点路由函数名与 `api.routes` 现有函数无冲突（create_note 已存在，新增 create_todo 等不重名）。✓
- `Note.fromSearchJson` 用 `note_id`（字符串）→ int，与后端 `semantic.search_notes` 返回形状一致。✓
