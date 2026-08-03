# Phase 2 长期记忆系统 — 设计文档

日期：2026-08-03
状态：已与用户确认

## 1. 背景与目标

Phase 1 demo 已完成：FastAPI 后端 + Web 聊天页 + DeepSeek（OpenAI 兼容接口），单容器 `docker compose up -d` 运行。

Phase 1 的最大缺陷：对话历史存在**进程内存**（`memory/store.py`），容器一重启就"失忆"。且 AI 只能看到当前会话，无法回忆过去任何会话的信息。

Phase 2 目标：按项目规划文档（`Personal_AI_OS_Project_Plan.md` Phase 2）实现三层长期记忆：

- 短期记忆：当前上下文（Redis）
- 长期语义记忆：兴趣/偏好/工作内容/习惯（Qdrant 向量检索）
- 结构化记忆：用户信息/家庭设备/任务记录（PostgreSQL）

用户已确认的关键决策：
1. 范围：**完整三层**（Redis + Qdrant + Postgres），全部 docker-compose 拉起
2. 记忆机制：**整段对话向量化**（不做 LLM 抽取事实），每轮结束把消息写入向量库，每轮开始向量检索 top-k 注入 system prompt
3. Embedding：**本地 fastembed + BAAI/bge-small-zh-v1.5**（ONNX，离线，免额外 key，中文优化，512 维，~90MB）
4. 检索范围：**全局跨会话**（这才是"长期记忆"的语义）

## 2. 总体架构

```
ai-backend (:8000)  ──  PostgreSQL (:5432)   持久化：sessions + messages（全量）
        │            ──  Redis (:6379)       短期：session 近期上下文缓存
        │            ──  Qdrant (:6333)      长期语义：消息向量 + 检索
        │
        └── 本地 embedding 模型（fastembed + bge-small-zh-v1.5，容器内离线）
```

三层分工：

| 层 | 服务 | 存什么 | 使用者 |
|---|---|---|---|
| 短期记忆 | Redis | 每个 session 最近 ~20 条消息（JSON 列表） | 快速取当前上下文 |
| 长期语义记忆 | Qdrant | 每条消息的向量 + payload（session_id/role/content/ts） | 每轮向量检索 top-k 相关记忆 |
| 结构化记忆 | PostgreSQL | sessions 表 + messages 表（全量消息） | 持久化；Redis 未命中时回源；重启不丢 |

## 3. 数据流

### 写路径（每轮回复完成后）

1. **Postgres**：事务内写入 user 消息 + assistant 回复，upsert session
2. **Redis**：更新该 session 近期上下文缓存（截断到最近 20 条）
3. **Qdrant**：对 user 消息和 assistant 回复分别 embedding → upsert 向量点

### 读路径（每轮对话开始前）

1. **近期上下文**：Redis 命中直接用；未命中从 Postgres 加载最近 N 条并回填 Redis
2. **语义记忆**：embedding 当前用户消息 → Qdrant 全局检索 top-5（相似度阈值过滤）→ 组装记忆块
3. **组装**：`system prompt + 记忆块 + 近期历史 + 新用户消息` → 流式回复

### 记忆注入格式（追加进 system prompt）

```
以下是检索到的历史记忆：
- [2026-08-03] 用户说：我喜欢喝美式咖啡
请结合这些记忆回答，但不要编造记忆里没有的内容。
```

## 4. 组件设计

### 4.1 database/db.py（重写：SQLite → PostgreSQL）

- 依赖 `psycopg[binary]>=3.2`（async 模式）
- 连接串从 `AI_DATABASE_URL`（默认 `postgresql://ai:ai@localhost:5432/ai`）读取
- 表：
  - `sessions(id text pk, created_at timestamptz, updated_at timestamptz)`
  - `messages(id bigserial pk, session_id text references sessions, role text, content text, created_at timestamptz)`
  - 索引：`messages(session_id)`
- 方法（保持 Phase 1 调用方兼容）：`init_db`, `upsert_session`, `list_sessions`, `session_exists(session_id)`, 新增 `load_recent_messages(session_id, limit)`, `append_messages(session_id, [msg...])`
- SQLite 的 `ai.db` 与 `DB_PATH` 逻辑删除

### 4.2 memory/short_term.py（新增）

- Redis 短期上下文。依赖 `redis>=5.0`，连接串 `REDIS_URL`（默认 `redis://localhost:6379/0`）
- key：`session:{id}:context`，value：JSON 数组（最近 N 条消息）
- 方法：`get_context(session_id)`, `set_context(session_id, messages)`, `delete_context(session_id)`

### 4.3 memory/semantic.py（新增）

- 依赖 `fastembed>=0.4`, `qdrant-client>=1.12`
- embedding 模型：`BAAI/bge-small-zh-v1.5`，512 维，cosine
- Qdrant：URL `QDRANT_URL`（默认 `http://localhost:6333`），collection 名 `conversation_memories`（启动时 ensure 存在）
- 点 payload：`{session_id, role, content, created_at}`
- 方法：
  - `store_message(session_id, role, content, created_at)` → embed + upsert
  - `recall(query_text, top_k=5, threshold=0.35)` → embed query → search → 过滤低于阈值的 → 返回 `[{content, role, created_at, score}]`
- embedding 计算封装在内部 `_embed(texts) -> list[list[float]]`，供测试 mock

### 4.4 api/routes.py（改造）

- 读路径：
  - `short_term.get_context(session_id)`；未命中回源 `db.load_recent_messages(session_id, limit)` 并 `short_term.set_context`
  - `semantic.recall(message)` 组装记忆块
  - 调 `agent.stream_chat(history, memory_context=...)`
- 写路径（流结束后）：
  - `db.append_messages(session_id, [user, assistant])` + `db.upsert_session`
  - `short_term.set_context(最近 20 条)`
  - `semantic.store_message` × 2（user + assistant）
- `db.session_exists(session_id)` 查 Postgres `sessions` 表（保持 `/api/sessions`、404 行为不变）
- 记忆检索失败不阻断对话：`semantic`/`short_term` 异常时降级为仅用近期上下文（记日志）

### 4.5 agent/chat_agent.py（小改）

- `stream_chat(messages, memory_context: str | None = None)`：有记忆块时拼进 system prompt

### 4.6 memory/store.py（删除）

- 原内存 store 功能被 `memory/short_term.py` + `database/db.py` 取代

### 4.7 docker-compose.yml

新增 3 个服务（均带数据卷）：

```yaml
postgres:
  image: postgres:16-alpine
  environment: { POSTGRES_USER: ai, POSTGRES_PASSWORD: ai, POSTGRES_DB: ai }
  volumes: [ pgdata:/var/lib/postgresql/data ]
  ports: [ "5432:5432" ]

redis:
  image: redis:7-alpine
  volumes: [ redisdata:/data ]
  ports: [ "6379:6379" ]

qdrant:
  image: qdrant/qdrant:v1.12.4
  volumes: [ qdrantdata:/qdrant/storage ]
  ports: [ "6333:6333" ]

ai-backend:
  depends_on: [ postgres, redis, qdrant ]
  environment:
    AI_DATABASE_URL: postgresql://ai:ai@postgres:5432/ai
    REDIS_URL: redis://redis:6379/0
    QDRANT_URL: http://qdrant:6333
```

### 4.8 .env(.example)

新增：`AI_DATABASE_URL`, `REDIS_URL`, `QDRANT_URL`, `MEMORY_TOP_K=5`, `MEMORY_THRESHOLD=0.35`, `HF_ENDPOINT=https://hf-mirror.com`

### 4.9 Dockerfile

- 构建时预下载 embedding 模型：`ENV HF_ENDPOINT=https://hf-mirror.com`，`RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-zh-v1.5')"`，模型缓存进镜像
- requirements 增加：psycopg[binary], redis, qdrant-client, fastembed
- 镜像体积增加 ~150-250MB（onnxruntime + 模型），远小于 sentence-transformers+torch 路线

## 5. 测试与验证

### 单元测试（mock，不依赖真实服务）

- `test_semantic.py`：mock `_embed` 与 Qdrant client，验证 recall 阈值过滤、store_message 的 upsert 参数
- `test_short_term.py`：mock Redis，验证 get/set/截断
- `test_db.py`：用测试库（真实 Postgres 或 monkeypatch psycopg）验证 append/load/list —— 优先用 mock 抽象，避免测试依赖真实服务
- `test_api.py`：沿用 fake agent + fake memory 层，验证读路径组装、记忆注入、降级路径

### 集成验证（真实服务，docker compose up 后）

1. 重启容器 → 问之前聊过的事（Postgres 持久化）
2. 开**新 session** → 问旧 session 提过的偏好（Qdrant 跨会话记忆）
3. 记忆探针：新对话里问"你知道我喜欢什么" → 答出旧会话提过的偏好
4. `/api/sessions`、`/api/health` 正常

## 6. 不做（本次范围外）

- LLM 抽取事实（facts 表）—— 用户选定整段向量化
- 记忆管理 UI / 手动增删记忆
- 多用户隔离（单用户个人 AI）
- Redis 持久化（纯缓存，重启清空由 Postgres 兜底）
