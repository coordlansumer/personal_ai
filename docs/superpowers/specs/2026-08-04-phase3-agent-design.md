# Phase 3 Agent 工具调用 — 设计文档

日期：2026-08-04
状态：已与用户确认

## 1. 背景与目标

Phase 2 已完成：三层记忆（PostgreSQL + Redis + Qdrant）跑在 Docker compose 里，`/api/chat` 是纯流式对话。`agent/chat_agent.py` 把 history 直接发给 DeepSeek，无工具调用能力。

Phase 3 目标：按项目规划文档（`Personal_AI_OS_Project_Plan.md` Phase 3），从聊天机器人升级为任务执行系统：

```
用户目标 → Agent规划 → 调用Tool → 执行 → 返回结果
```

用户已确认的关键决策：
1. 工具范围：**内置实用工具**——时间/日期、计算器、待办/提醒、备忘录（零外部依赖，完整演示闭环）
2. Agent 循环：**响应式循环**（标准 OpenAI function calling loop，非显式计划再执行）
3. 待办深度：**纯记录**，不做定时推送（那是 Phase 4 多终端的事）
4. 备忘录：**同步进 Qdrant 语义记忆**（独立 `note_memories` 集合），且聊天页加 **UI 直录按钮**（原话直录，不经 LLM）
5. 实现架构：**方案 B**——独立 `tools/` 层 + `agent/orchestrator.py` 循环层
6. 模型迁移：DeepSeek 旧模型名 `deepseek-chat`/`deepseek-reasoner` 已于 2026-07-24 退役，迁移到 **`deepseek-v4-flash`**

## 2. 总体架构

```
ai-backend (:8000)
    ├── api/routes.py          ── SSE 会话流（token + tool 事件）、POST /api/notes
    ├── agent/orchestrator.py  ── 响应式工具调用循环（≤5 轮）
    ├── agent/chat_agent.py    ── stream_chat() 支持 tools，统一走流式
    ├── tools/                 ── 工具注册表 + 4 个工具模块（9 个函数）
    ├── database/              ── db.py(sessions/messages) + todos.py + notes.py
    └── memory/semantic.py     ── 新增 note_memories 集合（store_note/search_notes/delete_note）
```

新目录/文件：

```
backend/
├── tools/
│   ├── __init__.py
│   ├── registry.py       # 工具注册表：to_openai_tools() + dispatch()
│   ├── basic.py          # now()
│   ├── calculator.py     # calculate()
│   ├── todo.py           # create/list/complete/delete_todo
│   └── notes.py          # create/search/delete_note
├── agent/orchestrator.py # 新增
├── database/todos.py     # 新增
├── database/notes.py     # 新增
```

## 3. 工具定义

每个工具是一个 dict，registry 统一管理：

```python
Tool = {
    "name": str,            # 如 "create_todo"
    "description": str,     # 给 LLM 看，何时用
    "parameters": dict,     # JSON Schema
    "handler": async fn(**kwargs) -> JSON 可序列化结果
}
```

- `registry.to_openai_tools()` → DeepSeek 要的 `tools` payload
- `registry.dispatch(name, args)` → 解析参数、调用 handler、捕获异常转 error 结果

### 3.1 工具清单（9 个，始终全部注册）

| 工具 | 参数 | 用途 | 说明 |
|---|---|---|---|
| `now` | 无 | 当前时间/日期/星期 | LLM 算"明天""下周三" |
| `calculate` | `expression: str` | 安全表达式求值 | ast 白名单，绝不用 eval/exec |
| `create_todo` | `title: str, due_at?: str(ISO), category?: str` | 新建待办 | 时间由 LLM 转 ISO 传入 |
| `list_todos` | `status?: str(pending\|done)` | 查待办 | 可按状态过滤 |
| `complete_todo` | `id: int` | 完成待办 | |
| `delete_todo` | `id: int` | 删待办 | |
| `create_note` | `content: str` | 记备忘 | Postgres + 嵌入 Qdrant |
| `search_notes` | `query: str, top_k?: int` | 语义搜备忘 | Qdrant `note_memories` 检索 |
| `delete_note` | `id: int` | 删备忘 | Postgres + Qdrant 双向删 |

### 3.2 calculate 安全约束

- 用 `ast.parse` 解析表达式，只允许：字面量（数字）、`BinOp` 的四则/取余/乘方、`UnaryOp`、括号（`Expr`/`BinOp` 结构）
- 任何函数调用（`Call`）、属性访问（`Attribute`）、导入、`Name`（变量）、布尔/字符串字面量 → 直接拒绝
- 返回 `{"result": ...}` 或 `{"error": "不支持的表达式"}`
- 绝不使用 `eval()` / `exec()`

### 3.3 search_notes 与会话记忆分离

- `note_memories` 是**独立 Qdrant 集合**，payload `{note_id, content, created_at}`
- 现有 `semantic.recall` 只搜 `conversation_memories`，互不干扰
- `semantic.py` 新增：`ensure_notes_collection()`、`store_note(note_id, content)`、`search_notes(query, top_k)`、`delete_note(note_id)`（点级删除需记 note_id 到 payload，用 payload 过滤删点）

## 4. 数据流

### 4.1 orchestrator 响应式循环

```
messages = [*recent_context, user消息]   + 记忆块注入 system prompt
for round in range(MAX_TOOL_ROUNDS):     # MAX_TOOL_ROUNDS = 5
    stream = llm.stream(messages, tools) # 流式调用
    tool_calls = {}; has_content = False
    async for chunk in stream:
        if delta.content:
            has_content = True
            yield SSE token 事件
        if delta.tool_calls:
            按 index 累积 {id, name, args片段}
    if not tool_calls: break              # 已产出最终答案
    for call in tool_calls:
        args = json.loads(call.args)       # 失败则 error 结果
        result = await registry.dispatch(call.name, args)
        yield SSE tool 事件 {name, arguments, result}
        messages += [assistant(tool_calls=...), tool(tool_call_id, json.dumps(result))]
```

- 工具结果以 `role:"tool"` 喂回 LLM（tool_call_id 对应）
- DeepSeek 流式支持 tool_calls delta，单轮响应要么内容要么 tool_calls

### 4.2 SSE 事件协议

现有：`session` / `token` / `error` / `done`。新增：

```
{"type": "tool", "name": "create_todo", "arguments": {...}, "result": {...}}
```

### 4.3 持久化边界

- 落库的只有最终 **user + assistant 文本**（现有路径不变：`db.append_messages` → Redis 上下文 → `semantic.store_message`）
- **工具调用与结果不写进 messages**——过程产物，todos/notes 表才是持久记录
- 历史上下文保持干净，AI 不被工具调用刷屏

### 4.4 UI 直录按钮（不经 LLM）

- 新端点：`POST /api/notes`，body `{content}` → 复用 `database/notes.py.create_note()` → 返回 `{id, content, created_at}`
- `create_note` 工具 handler 与这个端点走**同一条写入路径**（Postgres + 嵌入 Qdrant）

## 5. 数据库

新增两张表（`database/db.py.init_db()` 一并建）：

```sql
CREATE TABLE todos (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done
    category TEXT,
    due_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE TABLE notes (
    id BIGSERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`database/todos.py`：`create_todo`、`list_todos(status?)`、`complete_todo(id)`、`delete_todo(id)`
`database/notes.py`：`create_note(content) -> dict`、`get_note(id)`、`delete_note(id)`

## 6. ChatAgent 改动

- `stream_chat` 增加 `tools` 参数：每轮循环统一走流式调用
  - 工具选择轮：yield 无内容 token，orchestrator 从 chunk delta 累积 `tool_calls`
  - 最终答案轮：正常 yield 内容 token
- 不新增非流式方法——所有轮统一走流式，减少分支
- `DEFAULT_MODEL`：`deepseek-chat` → `deepseek-v4-flash`（保留 `DEEPSEEK_MODEL` 环境变量覆盖）
- `.env.example` 同步更新 model 默认值

## 7. 前端（index.html）

- 新增 `tool` 事件渲染：灰色小卡片 `🔧 create_todo(标题: 明天买牛奶)` + 结果摘要
- 输入框旁加"记笔记"按钮：点击 → `POST /api/notes` 存当前输入 → 显示"已记录"确认，清空输入框
- 其余交互不变

## 8. 错误处理

- 工具执行失败 → dispatch 捕获 → `{"error": "..."}` 作为 tool 结果回给 LLM，循环继续，AI 向用户说明
- 参数解析失败 / 未知工具名 → 同样转 error 结果
- 轮数耗尽（5 轮）→ 强制结束，追加"工具调用已达上限，请基于已有信息回答"再流式输出
- LLM 调用失败 → 现有 `LLMError` → SSE `error` 事件
- 工具调用失败不阻断：单工具出错不影响其他并行工具与最终回复

## 9. 测试与验证

### 单元测试（mock，不依赖真实服务）

- `test_calculator.py`：合法（`2+3*4`、`2**10`、`(1+2)*3`）/ 非法（空、未知符号）/ 注入（`__import__`、`os.system`、属性访问、内置函数、变量名）全拒绝
- `test_registry.py`：`to_openai_tools` 生成格式、`dispatch` 分发、未知工具、参数解析失败
- `test_todos.py`：mock db 层，验证 create/list/complete/delete 与状态过滤
- `test_notes.py`：mock db + 语义层，验证 create 落库并嵌入、search 检索、delete 双删
- `test_orchestrator.py`：fake LLM 脚本化返回（先 tool_calls 再 content），验证循环、tool 事件、轮数上限、失败降级
- `test_api.py`：更新覆盖 tool 事件、`POST /api/notes` 端点

### 集成验证（docker compose 起栈后）

1. "记下：明天下班买咖啡豆" → 应触发 create_note，`notes` 表有记录
2. 新会话 "搜我的备忘里关于咖啡的" → search_notes 召回
3. "明天下午3点提醒我开会" → now() 算日期 → create_todo
4. "我有哪些待办" → list_todos
5. 点 UI 记笔记按钮直录 → notes 表 + Qdrant `note_memories` 都有
6. `/api/health` 显示 `deepseek-v4-flash`

## 10. 不做（本次范围外）

- 定时推送通知（Phase 4 多终端）
- 外部 API 工具（天气/搜索/日历）
- 工具调用历史展示页 / 待办管理 UI
- 多用户隔离
- 显式计划式规划（用户选定响应式循环）
