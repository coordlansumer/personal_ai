# Phase 4 Android App — 设计文档

日期：2026-08-04
状态：已与用户确认

## 1. 背景与目标

Phase 3 已完成：后端跑在 Docker compose 栈里（postgres + redis + qdrant + ai-backend），聊天已升级为任务执行 Agent——9 个内置工具、SSE 流式（session/token/tool/error/done 事件）、工具卡片前端、`POST /api/notes` 直录按钮、模型迁移到 `deepseek-v4-flash`。

Phase 4 按项目规划文档（`Personal_AI_OS_Project_Plan.md` Phase 4）是多终端支持。本次只做**第一块：Flutter 安卓 App**（在小米澎湃系统上运行/测试）。

用户已确认的关键决策：
1. **平台**：Flutter Android App，真机运行在小米澎湃系统（HyperOS）
2. **v1 范围**：聊天（流式 + 工具卡片 + 记笔记按钮 + 会话恢复）**+ 待办页（全 CRUD）** + 笔记页（列表 + 语义搜索 + 删除）
3. **鉴权**：v1 不做登录，信任局域网（后端现状即无鉴权，零改动）
4. **服务器地址**：App 设置页可改，`shared_preferences` 本地持久化，默认 `http://10.0.2.2:8000`（模拟器可直连；真机需改为电脑局域网 IP）
5. **实现架构**：**方案 A**——极简依赖 Flutter + 专用 REST 接口；SSE 用 `dart:io` HttpClient + `LineSplitter` 手写解析
6. **仓库**：monorepo，新增 `app/` 目录与 `backend/` 平级
7. **不提供云服务**：v1 全部在局域网/本机完成，客户端开发连本机后端即可；外网访问（Tailscale / VPS）后置，不影响代码架构

## 2. 总体架构

```
backend/  (现有，只加 REST 接口层)
    api/routes.py          ── 新增 todos/notes 的 REST 端点（复用 database 层 + jsonable_row）
    database/todos.py      ── 复用
    database/notes.py      ── 复用
    memory/semantic.py     ── 复用（notes 搜索走 semantic.search_notes）

app/     (新增，Flutter Android)
    lib/                   ── 3 个页面 + 设置页 + 服务层 + 状态层
    android/               ── Flutter 默认安卓工程（打开明文 HTTP）
```

手机 App（Flutter）↔ `http://<服务器IP>:8000/api/*` ↔ 后端（Docker compose）。聊天走 SSE 流式，待办/笔记走 REST JSON。

## 3. 后端新增 REST 接口

全部复用 `database.todos` / `database.notes` + `tools.jsonable_row`（datetime→ISO 字符串），返回结构与现有工具保持一致，错误走 HTTP 状态码。

| 接口 | 请求 | 成功返回 | 错误 |
|---|---|---|---|
| `GET /api/todos` | query `status?=pending\|done` | `{"todos":[{id,title,status,category,due_at,created_at,completed_at}...], "count":n}` | — |
| `POST /api/todos` | `{title: str, due_at?: str(ISO), category?: str}` | 新行（jsonable_row） | 400 内容为空 |
| `POST /api/todos/{id}/complete` | — | `{"completed": true, "id": id}` | 404 不存在 |
| `DELETE /api/todos/{id}` | — | `{"deleted": true, "id": id}` | 404 不存在 |
| `GET /api/notes` | — | `{"notes":[{id,content,created_at}...], "count":n}` | — |
| `GET /api/notes/search` | query `q=&top_k?=5` | `{"hits":[{note_id,content,created_at,score}...], "count":n}` | — |
| `DELETE /api/notes/{id}` | — | `{"deleted": true, "id": id}` | 404 不存在 |

说明：
- `POST /api/notes` 已存在（Phase 3），复用。
- complete/delete 先查存在性，不存在抛 404。
- notes 搜索直接调 `semantic.search_notes(q, top_k)`（Qdrant 语义检索，不经 LLM）。
- 新增端点放入 `api/routes.py`（或按需拆 `api/todos.py` / `api/notes.py`，实现时按文件大小判断）。

## 4. Flutter App 结构

依赖仅 3 个：`provider`、`http`、`shared_preferences`。SSE 解析手写，不引第三方 SSE 包。

```
app/lib/
    main.dart              — MaterialApp（Material 3）、Provider 装配、启动后读设置
    home_shell.dart        — 底部导航：聊天 / 待办 / 笔记 三 Tab + AppBar 右上角设置入口
    models/
        todo.dart          — Todo.fromJson / toJson
        note.dart          — Note.fromJson（search hit 与列表行可共用一个模型）
        chat_message.dart  — ChatMessage(role,content)、ToolCall(name,arguments,result)
    services/
        api_client.dart    — baseUrl（从 SettingsService 读）；todos/notes 的 REST 方法；非 2xx 抛 ApiException(detail)
        chat_service.dart  — stream(text, sessionId) → Stream<ChatEvent>，手写 SSE 解析
        settings_service.dart — shared_preferences 读写 serverUrl（默认 http://10.0.2.2:8000）
    state/
        chat_controller.dart   — ChangeNotifier：messages、isStreaming、sessionId、send()、记录笔记
        todos_controller.dart  — ChangeNotifier：todos、loading、error、load/create/complete/delete
        notes_controller.dart  — ChangeNotifier：notes、loading、error、load/search/delete
    screens/
        chat_screen.dart       — 消息列表（AI 气泡 / 用户气泡 / 工具卡片 / 错误气泡）+ 输入框 + 记笔记按钮
        todos_screen.dart      — ListView + 新建对话框 + 完成 checkbox + 滑动删除 + 下拉刷新 + 空态
        notes_screen.dart      — 顶部搜索框 + ListView + 滑动删除 + 空态 + 下拉刷新
        settings_screen.dart   — 服务器地址文本框，保存到 shared_preferences
```

导航：底部 NavigationBar 三 Tab；设置入口放 AppBar 图标。待办/笔记页打开时加载数据，提供下拉刷新。

## 5. 数据流

### 5.1 聊天（SSE）

1. 用户发消息 → `chat_controller.send(text)` 追加用户气泡 + 新建空 AI 气泡
2. `chat_service.stream(text, sessionId)` 发起 `POST /api/chat`，Content-Type: application/json，`Accept: text/event-stream`
3. 用 `dart:io` HttpClient：`response.transform(utf8.decoder).transform(const LineSplitter())` 逐行解析
   - `data: {json}` 行 → jsonDecode；空行 → 事件结束（每事件单行 data）
4. 事件分发：
   - `session` → 记录 `sessionId`（本会话内跨消息恢复上下文）
   - `token` → 追加内容到当前 AI 气泡
   - `tool` → 渲染工具卡片（名称 / 参数 / 结果，灰色卡片）
   - `error` → 红色错误气泡
   - `done` → 结束流式状态
5. 「记笔记」按钮：取输入框内容 POST `/api/notes`（不经 LLM）→ Snackbar「已记录到笔记」

### 5.2 待办 / 笔记（REST）

- 待办：打开加载 `GET /api/todos`；新建对话框 → `POST /api/todos`；完成 checkbox → `POST /api/todos/{id}/complete`；滑动删除 → `DELETE /api/todos/{id}`；每次操作后重拉列表。
- 笔记：打开加载 `GET /api/notes`；搜索框（防抖/提交）→ `GET /api/notes/search?q=`；滑动删除 → `DELETE /api/notes/{id}`；删除后重拉。

## 6. 错误处理与边界

- 服务器连不上：各页显示错误态 + 重试按钮；聊天流连接失败 → 错误气泡。
- REST 非 2xx：`ApiException` 携带后端 `detail`（如「内容不能为空」），Snackbar 展示。
- 空列表：「暂无待办」「暂无笔记」空态。
- SSE `error` 事件：红色错误气泡（显示后端错误信息）。
- Android 9+ 默认禁明文 HTTP：`AndroidManifest.xml` 设 `android:usesCleartextTraffic="true"`（局域网开发用）。
- 服务器地址非法/连不通：设置页保存时校验格式，聊天/列表页错误态引导去设置。

## 7. 配置与工具链

- 服务器地址：设置页编辑，存 `shared_preferences`；App 启动时读出注入 ApiClient。改完回聊天页生效。
- 本机工具链（实施 Task 0）：装 Flutter SDK + Android SDK（含 platform-tools），或用用户指定的另一台已装好的机器；真机需开启 USB 调试（小米澎湃系统 Developer options）。
- 默认地址 `http://10.0.2.2:8000`（安卓模拟器指宿主机 localhost）；真机改为电脑局域网 IP。

## 8. 测试策略

- **后端**：pytest 新增 `tests/test_api_todos.py`、`tests/test_api_notes.py`，沿用 FakeConn 模式，覆盖列表/新建/完成/删除/404/搜索/空内容 400。
- **Flutter 单元**：SSE 解析器测试（喂 `data: {...}` 样例行，断言事件序列）；模型 fromJson 测试。
- **Flutter widget**：待办页/笔记页用 mock ApiClient 测试加载/空态/删除交互；聊天页用 fake ChatService 测试气泡与工具卡片渲染。
- **真机集成**：USB 调试跑在小米手机上，手工验证——聊天流式、工具卡片、记笔记按钮、待办 CRUD、笔记列表/搜索/删除、设置页改地址。

## 9. 明确不做（YAGNI）

- 登录/账号体系（v1 信任局域网；「多端同账号」留到以后）
- 外网访问/HTTPS/云部署（Tailscale 或 VPS 后置，不动代码架构）
- 桌面端 / Web 工程化前端（Phase 4 后续块）
- 待办定时推送（Phase 3 就已明确是纯记录）
- 推送通知、离线缓存、多主题等（无需求不加）
- 第三方 SSE 包 / 重型状态管理（保持极简依赖）
