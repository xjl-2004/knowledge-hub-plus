# knowledge-hub-plus 实施计划

> 目标：在 `knowledge-hub-plus/` 下以 **Python + FastAPI** 重建后端，前端保持原样，API 契约、数据模型与业务行为与既有系统完全一致。
>
> 本文档只描述实施方案，不包含任何代码实现。

---

## 1. 背景与目标

现有系统由 `knowledge-hub/knowledge-hub-backend`（NestJS + TypeScript）与 `knowledge-hub/knowledge-hub-frontend`（React 19 + Vite）组成，提供企业知识库的文档管理、审核流转、全文/向量混合检索、知识图谱与 Agentic RAG 对话能力。

本次工作的目标是：

1. 将后端技术栈替换为 **Python 3.12 + FastAPI**，保留全部对外能力；
2. 前端代码、依赖、构建配置与页面逻辑保持不变，仅作为整体落位到新工程；
3. 按可独立运行、可验证的粒度分阶段推进，每个阶段产出一个规范的 git commit；
4. 交付物中不出现 "复刻 / 克隆 / 副本" 等描述性字眼，统一使用 "实现 / 搭建 / 接入 / 完善"。

### 1.1 成功标准

- 前端不做任何源码改动，即可完成登录、文档、搜索、图谱、AI 对话全部流程；
- 所有 HTTP 路由、请求体字段、响应字段名（camelCase）、错误结构、ID 字符串化行为与现网一致；
- SSE 流式对话可被 `@ai-sdk/react` 的 `useChat` 正常消费；
- 初始化脚本中的表结构、种子账号、角色权限在新后端下可直接使用；
- `docker compose up` 后各中间件可用，`uvicorn` 单进程即可跑通全部功能。

### 1.2 非目标

- 不新增产品功能、不改前端交互、不改数据库既有字段语义；
- 不引入新的鉴权方式、不做服务拆分、不做多租户改造；
- 不重写初始化 SQL 的业务含义（仅做必要的 Python 侧 ORM 映射）；
- 不实现 README 中与代码实际行为不一致的 "哈希向量降级"（以实际代码为准，见 §10.2）。

---

## 2. 硬性约束

| 编号 | 约束 | 落地方式 |
| --- | --- | --- |
| C1 | 后端必须是 Python + FastAPI | FastAPI + Uvicorn + Pydantic v2 + SQLAlchemy 2.x async |
| C2 | 前端不变 | `frontend/` 下文件与源目录逐字节一致，仅剔除 `node_modules`、`dist` |
| C3 | 分阶段提交 | 每个阶段独立可运行，提交信息符合 Conventional Commits |
| C4 | 禁用字眼 | 代码、注释、提交信息、README 中不得出现"复刻/克隆/副本/复刻版" |
| C5 | 端口不变 | 后端监听 `3000`，前端 Vite 代理无需改动 |
| C6 | 路由前缀不变 | FastAPI 直接暴露无 `/api` 前缀的路由（Vite 代理负责剥离） |

---

## 3. 技术选型

| 能力 | 选型 | 说明 |
| --- | --- | --- |
| Web 框架 | FastAPI 0.115+ / Uvicorn | 单进程 + `--reload` 开发 |
| 配置 | pydantic-settings | 读取 `.env`，字段名与现有 `.env.example` 对齐 |
| 校验 | Pydantic v2 | 自定义异常处理器输出 `{ message: string \| string[] }` |
| ORM | SQLAlchemy 2.0 async + asyncpg | 显式映射既有表，`Alembic` 仅用于校验/增量，不重建业务表 |
| PostgreSQL | pgvector:pg16 | 沿用现有 `init.sql` |
| MongoDB | motor | 集合 `document_content` |
| Redis | redis-py (async) | 验证码、激活 token、短期记忆 |
| Elasticsearch | elasticsearch-py 8.x | 索引 `kh_document`、`kh_chunk`，IK 分词 |
| Neo4j | neo4j 官方 driver (async) | 图模型不变 |
| RabbitMQ | aio-pika | topic exchange + 持久化队列 |
| 对象存储 | aioboto3 (S3 兼容) | RustFS，bucket `knowledge-hub` |
| JWT | PyJWT | access/refresh 双 token，`type` 区分 |
| 密码 | passlib[bcrypt] / bcrypt | 兼容既有 `$2b$` 哈希 |
| LLM | openai SDK（DashScope 兼容端点） | 不强制依赖 LangChain |
| 重排 | httpx 调 DashScope text-rerank | 失败降级为 RRF 分数 |
| 文档解析 | pypdf、python-docx、openpyxl、python-pptx、markdownify | 统一输出 Markdown |
| 雪花 ID | 自实现 64 位 | 41 位时间戳 + 10 位 worker + 12 位序列 |
| 测试 | pytest + pytest-asyncio + httpx ASGITransport | 接口级契约测试 |
| 依赖管理 | uv + `pyproject.toml` | 锁定 `uv.lock` |

---

## 4. 目标目录结构

```
knowledge-hub-plus/
├── plan.md
├── README.md
├── .gitignore
├── docker-compose.yml
├── init-scripts/
│   ├── postgresql/init.sql
│   └── mongodb/init.js
├── deploy/
│   └── elasticsearch/Dockerfile
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .env.example
│   ├── alembic.ini
│   ├── app/
│   │   ├── main.py                # create_app、CORS、异常处理、路由注册
│   │   ├── core/
│   │   │   ├── config.py          # Settings
│   │   │   ├── security.py        # JWT 签发/校验、bcrypt
│   │   │   ├── snowflake.py       # 64 位 ID
│   │   │   ├── errors.py          # 异常类型 + 全局 handler
│   │   │   ├── deps.py            # 当前用户、权限依赖
│   │   │   └── logging.py
│   │   ├── db/
│   │   │   ├── session.py         # async engine / session
│   │   │   ├── mongo.py
│   │   │   ├── redis.py
│   │   │   ├── es.py
│   │   │   ├── neo4j.py
│   │   │   ├── amqp.py
│   │   │   └── s3.py
│   │   ├── models/                # SQLAlchemy 实体（逐表映射）
│   │   ├── schemas/               # Pydantic 请求/响应
│   │   ├── routers/               # auth/users/roles/permissions/teams/documents/search/graph/ai
│   │   ├── services/              # 业务逻辑
│   │   ├── integrations/          # llm / rerank / web-search / parser / mail
│   │   └── pipeline/              # chunking / embedding / index / graph / mq consumer
│   └── tests/
└── frontend/                      # 与源前端逐文件一致
```

---

## 5. 兼容性契约

### 5.1 HTTP 约定

- 后端监听 `3000`；FastAPI 路由**不带** `/api` 前缀。
- 所有响应字段使用 **camelCase**（Pydantic `alias_generator=to_camel` + `populate_by_name`）。
- 所有实体主键（雪花 ID、Mongo `_id`）一律序列化为**字符串**。
- 时间字段为 ISO 8601 字符串，字段名与现网一致（`createdAt` / `updatedAt` / `publishTime`）。
- 分页响应统一为 `{ items, total, page, pageSize }`。

### 5.2 错误结构

前端 `api/client.ts` 只读取响应体的 `message` 字段：

```json
{ "message": "文档不存在" }
{ "message": ["title 不能为空", "status 取值非法"] }
```

| 场景 | 状态码 | 响应 |
| --- | --- | --- |
| 参数校验失败 | 400 | `{ "message": [ ... ] }` |
| 未登录 / token 失效 | 401 | `{ "message": "未授权" }` |
| 无权限 | 403 | `{ "message": "无权限" }` |
| 资源不存在 | 404 | `{ "message": "..." }` |
| 业务冲突 | 400 / 409 | `{ "message": "..." }` |
| LLM 未配置 | 503 | `{ "message": "未配置 OPENAI_API_KEY ..." }` |

> 必须覆盖 FastAPI 默认的 `{"detail": ...}` 与 422 结构，统一转换为上表格式。

### 5.3 CORS

`allow_origins=["*"]` 与 `credentials=True` 不能共存，需自定义：读取请求 `Origin` 并回显到 `Access-Control-Allow-Origin`，同时允许 `Authorization`、`Content-Type`，暴露全部响应头，支持 `OPTIONS` 预检。

### 5.4 鉴权

- `Authorization: Bearer <accessToken>`；全局守卫，登录/注册/刷新/验证邮箱/找回密码/健康检查放行。
- JWT payload：`{ sub, username, type: "access" | "refresh" }`。
- access 默认 2h、refresh 默认 7d，支持 `s/m/h/d` 后缀配置。
- 角色从 `kh_user_role` 关联 `kh_role.role_code` 得到；权限 = 直接权限 ∪ 角色权限；`ROLE_ADMIN` 额外追加管理类权限并跳过权限校验。
- 当前用户对象结构：`{ userId, username, realName, email, avatar, roles, permissions, teamIds }`。

### 5.5 流式对话（关键兼容点）

`POST /ai/chat/stream` 必须输出 AI SDK **UI Message Stream**：

- 响应头：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`Connection: keep-alive`、`X-Accel-Buffering: no`、`x-vercel-ai-ui-message-stream: v1`。
- 事件以 `data: {json}\n\n` 逐条发送，末尾 `data: [DONE]`。
- 需要输出的事件类型：`start`、`start-step`、`text-start` / `text-delta` / `text-end`、`finish-step`、`finish`，以及自定义 data part：`data-status`、`data-intent`、`data-eval`、`data-graph`、`data-sources`、`data-session`、`source-document`。
- 工具调用阶段需输出 `tool-input-start` / `tool-input-available` / `tool-output-available`。
- 客户端断开时取消下游 LLM 请求，并在 `finish` 前完成会话落库。

> 阶段 11 实现前，先逐行核对 `ai-stream.service.ts` 的实际事件载荷，以其为准。

### 5.6 其他前端依赖细节

- `DELETE /teams/:id/members` 携带 JSON body `{ userIds: string[] }`，FastAPI 需显式从 body 读取。
- 上传接口为 `multipart/form-data`，字段名 `file`，大小上限 50MB，超限返回 400。
- `GET /permissions/tree` 返回树形结构；`GET /teams/tree` 支持 `rootOnly=true`。
- `GET /documents/reviews/tasks` 必须先于 `GET /documents/{id}` 注册。
- `status` 取值：`0 Draft`、`1 Published`、`2 Archived`、`3 PendingReview`。
- `isPublic` 为布尔，查询参数接受 `"true"/"false"` 字符串。

---

## 6. 数据模型

### 6.1 PostgreSQL（沿用 `init-scripts/postgresql/init.sql`）

| 表 | 关键字段 |
| --- | --- |
| `kh_user` | id, username, password, real_name, email, avatar, status, email_verified, last_login_at, created_at, updated_at, deleted |
| `kh_role` | id, role_code, role_name, description, status, created_at, updated_at |
| `kh_user_role` | id, user_id, role_id |
| `kh_permission` | id, permission_code, permission_name, permission_type, parent_id, path, icon, sort, status |
| `kh_role_permission` | id, role_id, permission_id |
| `kh_user_permission` | id, user_id, permission_id |
| `kh_team` | id, team_name, team_code, parent_id, leader_id, description, status, deleted |
| `kh_team_member` | id, team_id, user_id, member_role |
| `kh_document` | id, title, content_id, summary, category_id, team_id, author_id, cover_image, tags, status, remark, view_count, like_count, comment_count, favourite_count, word_count, publish_time, is_public, created_at, updated_at, create_by, update_by, deleted |
| `kh_document_review` | id, document_id, reviewer_id, reviewer_name, review_result, review_comment, before_status, reviewed_at, created_at |
| `kh_ai_session` | id, user_id, title, created_at, updated_at |
| `kh_ai_message` | id, session_id, role, content, sources (JSONB), created_at |

映射原则：

- 表名、列名不做改名；`deleted` 采用软删标记，查询条件统一 `deleted = false`；
- `content_id` 存 Mongo `document_content._id` 的字符串形式；
- 所有主键为 `BIGINT`，ORM 层以 `int` 处理，序列化层转 `str`；
- 事务边界放在 service 层，Mongo 与 PG 的双写失败需回滚（先删正文再删元数据）。

### 6.2 MongoDB

集合 `document_content`：

```
{ _id, documentId, content, contentLength, contentSummary, version, deleted, createdAt, updatedAt }
```

- 正文更新：`$set { content, contentLength, contentSummary }` + `$inc { version: 1 }`；
- 软删与 PG 同步；读取失败时文档详情返回 404。

### 6.3 Redis

| Key | 用途 | TTL |
| --- | --- | --- |
| `email:activation:token:<token>` | 邮箱激活 token → userId | 24h |
| `email:activation:user:<userId>` | 用户当前激活 token | 24h |
| `password:reset:code:<email>` | 找回密码验证码 | 600s |
| 短期记忆 key | 会话上下文（沿用现有前缀） | 86400s |

- 验证码发送冷却 60s：通过剩余 TTL > 540 判断；
- 阶段 2 与 11 分别核对 `email-activation.service.ts`、`password-reset.service.ts`、`chat-short-memory.service.ts` 的 key 拼接规则。

### 6.4 Elasticsearch

**索引 `kh_document`**：`title/summary/content` 写 `ik_max_word`、查 `ik_smart`；`title^3`、`summary^2`、`content` 的 `multi_match`；高亮字段 `title/summary/content`。

**索引 `kh_chunk`**：`embedding` 为 `dense_vector(dims=1024, similarity=cosine)`；混合检索为 `knn` + `multi_match`，用 RRF `1/(k+rank+1)` 融合；`document_id` 用于删除与可见性更新（`update_by_query`）。

### 6.5 Neo4j

```
(KnowledgeDocument)-[:HAS_CHUNK]->(DocumentChunk)-[:MENTIONS]->(KnowledgeEntity)
(KnowledgeEntity)-[:RELATED_TO]->(KnowledgeEntity)
```

- 重建流程：先 `DETACH DELETE` 旧文档与块，再 `MERGE` 写入；删除后清理孤儿实体；
- 所有查询都必须带可见性条件（`is_public` / `author_id` / `team_id`）。

### 6.6 RabbitMQ

| Exchange | Queue | Routing Key |
| --- | --- | --- |
| `rag.reindex.exchange` | `kh.rag.reindex.queue` | `rag.reindex.by_ids`、`rag.reindex.delete` |
| `search.index.exchange` | `kh.search.index.queue` | `search.index.document`、`search.index.delete` |
| `kg.graph.exchange` | `kh.kg.graph.queue` | `kg.graph.build.by_ids`、`kg.graph.delete` |

- 消息持久化、手动 ack；消费异常 `nack(requeue=False)`；
- 文档发布 `afterPublish` 并行投递三类任务，下线/归档 `afterUnpublish` 并行删除。

### 6.7 对象存储

- Bucket：`knowledge-hub`，启动时 `ensureBucket`；
- Key：`{prefix}/{yyyy}/{mm}/{dd}/{safeBase}-{uuid}{ext}`，文档正文附件前缀 `documents`，PDF 内嵌图片前缀 `pdf-images`；
- 访问 URL：`{publicBase}/{bucket}/{key}`。

---

## 7. API 清单（契约基线）

> 所有接口均为 JSON；标注 `公开` 的无需鉴权。

### 7.1 认证 `/auth`

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| POST | `/auth/register` | 公开 | 用户名 + 密码（≥6），可选邮箱/姓名 |
| POST | `/auth/login` | 公开 | 返回 `accessToken/refreshToken/tokenType/expiresIn/userInfo` |
| POST | `/auth/refresh` | 公开 | 校验 `type=refresh` |
| GET | `/auth/verify-email?token=` | 公开 | 激活邮箱 |
| POST | `/auth/password/reset/send-code` | 公开 | 发送验证码，60s 冷却 |
| POST | `/auth/password/reset` | 公开 | 校验验证码并改密 |
| POST | `/auth/logout` | 登录 | 清理登录态 |
| GET | `/auth/me` | 登录 | 当前用户 |
| GET | `/auth/reviewer-ids` | ADMIN/REVIEWER | 审核人列表 |

### 7.2 用户 `/users`

`PUT /users/me`、`GET /users/me/stats`、`PUT /users/password/change`、
`GET /users/page`、`GET /users/{id}`、`POST /users`、`PUT /users/{id}`、`DELETE /users/{id}`、
`PUT /users/{id}/password/reset`、`GET|PUT /users/{id}/roles`、`GET|PUT /users/{id}/permissions`。

### 7.3 角色 `/roles`

`GET /roles/list`、`GET /roles/{id}`、`POST /roles`、`PUT /roles/{id}`、`DELETE /roles/{id}`、`GET|PUT /roles/{id}/permissions`。

### 7.4 权限 `/permissions`

`GET /permissions/list`、`GET /permissions/tree`、`GET /permissions/page`、
`GET /permissions/{id}/children`、`GET /permissions/{id}`、`POST /permissions`、`PUT /permissions/{id}`、`DELETE /permissions/{id}`。

### 7.5 团队 `/teams`

`POST /teams`、`PUT /teams/{id}`、`DELETE /teams/{id}`、`GET /teams/page`、`GET /teams/mine`、
`GET /teams/tree`、`GET /teams/{id}`、`GET|POST|DELETE /teams/{id}/members`。

### 7.6 文档 `/documents`

| 方法 | 路径 | 权限 |
| --- | --- | --- |
| POST | `/documents` | `document:create` |
| POST | `/documents/upload/parse` | `document:create` |
| GET | `/documents/reviews/tasks` | `document:review` |
| GET | `/documents/reviews/tasks/pending-count` | `document:review` |
| POST | `/documents/reviews/tasks/{taskId}/approve` | `document:review` |
| POST | `/documents/reviews/tasks/{taskId}/reject` | `document:review` |
| GET | `/documents` | `document:list` |
| GET | `/documents/{id}` | 登录 + 读权限 |
| PATCH | `/documents/{id}` | `document:edit` + 写权限 |
| DELETE | `/documents/{id}` | `document:delete` + 写权限 |
| PUT | `/documents/{id}/publish` | `document:create` |
| PUT | `/documents/{id}/archive` | `document:edit` |
| PUT | `/documents/{id}/save-draft` | `document:edit` |
| POST | `/documents/{id}/reviews/submit` | `document:create` |
| GET | `/documents/{id}/reviews/current` | 登录 |
| GET | `/documents/{id}/reviews/history` | 登录 |

### 7.7 检索 / 图谱

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/search` | 全文检索，参数 `keyword/page/pageSize(≤50)/categoryId/authorId` |
| GET | `/graph/overview` | 图谱概览 |
| GET | `/graph/search?keyword=&limit=` | 实体检索 |
| GET | `/graph/nodes`、`/graph/edges` | 节点/边列表 |

### 7.8 AI

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/rag/search` | 混合检索，`topK ≤ 20` |
| POST | `/ai/chat` | 非流式，返回 `{ sessionId, answer, sources }` |
| POST | `/ai/chat/stream` | UI Message Stream |
| GET | `/ai/sessions` | 会话分页 |
| POST | `/ai/sessions` | 新建会话 |
| GET | `/ai/sessions/{id}` | 会话详情 |
| PATCH | `/ai/sessions/{id}` | 重命名 |
| DELETE | `/ai/sessions/{id}` | 删除会话及消息 |
| GET | `/ai/sessions/{id}/messages` | 会话消息 |

---

## 8. 分阶段实施计划

> 每个阶段以"可启动 + 可验证"为结束条件，结束即提交一次 commit。

### 阶段 0：工程初始化

**内容**
- 创建 `knowledge-hub-plus` git 仓库、`.gitignore`（排除 `node_modules`、`dist`、`.env`、`__pycache__`、`.venv`、`test-files`）
- `README.md`：架构说明、端口、预置账号（admin/reviewer/user，密码 `123456`）、启动步骤
- `backend/pyproject.toml`、`app/main.py` 应用工厂、`core/config.py`、`core/logging.py`
- `GET /` 与 `GET /health` 健康检查
- `pyproject` 脚本：`uv run uvicorn app.main:app --port 3000 --reload`

**验收**：`curl http://127.0.0.1:3000/health` 返回 200；无数据库依赖也能启动。

**提交**：`chore: 初始化 FastAPI 项目骨架与开发配置`

---

### 阶段 1：基础设施与数据访问层

**内容**
- `docker-compose.yml`、`init-scripts/`、`deploy/elasticsearch/`
- SQLAlchemy 异步引擎、会话依赖、全部实体映射（§6.1 表）
- Mongo / Redis / ES / Neo4j / RabbitMQ / S3 客户端封装，启动时可选连通性检查（失败仅告警）
- `.env.example`：字段与现有配置一一对应
- Alembic 基线（`alembic stamp head`，不生成新业务表）

**验收**：`docker compose up -d` 后各中间件健康；`uv run python -c "..."` 可完成一次 PG 查询、Redis 读写、ES ping、Neo4j verify。

**提交**：`feat(infra): 接入数据库与中间件客户端`

---

### 阶段 2：认证与令牌体系

**内容**
- bcrypt 校验、JWT 签发/解析、access/refresh 区分
- 全局鉴权依赖 + 公开路由白名单
- `auth` 路由全部接口、邮箱激活、找回密码（Redis + 冷却）
- 统一异常结构与 CORS 中间件
- 雪花 ID 生成器

**验收**
- `admin/123456` 登录成功，返回字段与前端 `LoginResult` 完全一致；
- access 过期后用 refresh 换取新 token；refresh 当作 access 使用返回 401；
- 错误响应体只含 `message`。

**提交**：`feat(auth): 实现注册登录与 JWT 令牌刷新`

---

### 阶段 3：RBAC 与用户/角色/权限

**内容**
- `kh_user` / `kh_role` / `kh_permission` 及关联表的 service
- 权限构建：直接权限 ∪ 角色权限，ADMIN 追加管理权限；`permissions` 依赖工厂
- 用户分页、增删改、重置密码、角色/权限分配、个人资料与统计
- 角色与权限的 CRUD、权限树、分页

**验收**
- 三种预置账号登录后 `permissions` 与 `roles` 与旧系统一致；
- 越权访问返回 403；`ADMIN` 跳过权限校验；
- 有子权限或已绑定的权限不可删除，有用户的角色不可删除。

**提交**：`feat(rbac): 实现用户角色权限管理与鉴权依赖`

---

### 阶段 4：团队与数据可见性

**内容**
- 团队 CRUD、`mine`、`tree`、成员增删查
- `listAccessibleTeamIds`：成员表 ∪ `leader_id`，过滤软删
- 文档可见性判定工具（读/写）

**验收**：团队成员能看到团队内文档；非成员访问返回 403；有子团队不可删除。

**提交**：`feat(team): 实现团队管理与成员维护`

---

### 阶段 5：文档模型、状态机与 CRUD

**内容**
- 文档创建/详情/分页/PATCH/软删；Mongo 正文读写与双写回滚
- 状态机：`Draft 0`、`Published 1`、`Archived 2`、`PendingReview 3`
- 列表可见性 SQL：`author_id = me OR (status = 1 AND (is_public OR team_id IN (...)))`
- `publish / archive / save-draft` 状态流转
- 字数统计、摘要生成（200 字截断）

**验收**
- 创建草稿、发布、归档、转草稿全链路可用；
- 无权限用户列表与详情均不可见；
- 双写失败时 Mongo 不残留孤儿正文。

**提交**：`feat(document): 实现文档创建编辑与状态流转`

---

### 阶段 6：文件解析与上传

**内容**
- `POST /documents/upload/parse`：`multipart` 字段 `file`，上限 50MB
- 解析器：PDF（pypdf，可提取图片并上传 `pdf-images/`）、DOCX、XLSX（openpyxl）、PPTX、TXT、MD
- 统一转 Markdown；空结果报 400
- 原文件上传 RustFS，创建草稿文档

**验收**：六种格式各上传一次，返回草稿文档且正文可在详情中读取；超限文件返回 400。

**提交**：`feat(document): 支持多格式文档解析与导入`

---

### 阶段 7：审核流程

**内容**
- 审核开关 `DOCUMENT_REQUIRE_APPROVAL`（默认开启）
- 提交审核、待办列表、待办数量、当前审核、审核历史
- 通过 → `Published` + `publishTime`；驳回 → `Draft`，意见必填
- 单一文档只允许一条 pending 记录；来自 `Published` 的提交需先清索引

**验收**：普通用户提交后进入 `PendingReview`；审核人通过后出现在列表；驳回后可再次编辑。

**提交**：`feat(review): 实现文档提交审核与审批流转`

---

### 阶段 8：消息队列与流水线骨架

**内容**
- RabbitMQ 拓扑声明、持久化发布、手动 ack
- `DocumentPipelinePublisher`：发布/下线时并行投递 RAG、Search、KG 任务
- Consumer 常驻消费，异常 `nack` 不重入
- `PipelineOrchestrator` 分发三类 handler（先接空实现 + 日志）

**验收**：发布文档后三个队列均收到消息并成功 ack；中间件宕机时发布接口不阻塞（记录告警）。

**提交**：`feat(pipeline): 搭建文档处理消息队列与任务分发`

---

### 阶段 9：全文检索与向量索引

**内容**
- `kh_document` 索引写入/删除、IK 检索、高亮、分页
- 分块：Markdown 递归切分（512/64），`chunkId = sha256("{documentId}:{index}")`
- 嵌入：DashScope `text-embedding-v3`，1024 维，批量 ≤ 10
- `kh_chunk` 写入、`knn` + 关键词双路召回、RRF 融合
- 可见性 `update_by_query`
- `POST /search`、`GET /rag/search`（rerank 前的基础版本）

**验收**：发布文档后可被关键词命中且高亮正确；`/search` 在 ES 不可用时返回空分页而非 500。

**提交**：`feat(search): 实现全文检索与向量索引流水线`

---

### 阶段 10：重排与 RAG 检索

**内容**
- DashScope rerank（`qwen3-rerank`），超时/失败降级为 RRF 分数
- 混合检索服务：查询向量化失败 → 仅关键词；`minScore` 过滤；`topK`
- 检索切题评估与不足改写（结构化输出，失败按召回放行）

**验收**：`/rag/search` 返回 `chunkId/documentId/documentTitle/content/heading/score`；无 LLM key 时仍可返回关键词结果。

**提交**：`feat(rag): 实现混合检索与重排评估`

---

### 阶段 11：知识图谱

**内容**
- 实体/关系抽取（结构化输出，实体 ≤12、关系 ≤15，时间截断 4000 字）
- 图构建/删除/孤儿清理
- `overview / search / nodes / edges` 查询（带可见性）
- 对话检索：短实体名匹配 → 命中文档子图 → 上下文格式化

**验收**：发布文档后图谱出现节点与边；删除文档后节点清理且无孤儿；非授权用户查询不返回数据。

**提交**：`feat(graph): 实现知识图谱构建与检索`

---

### 阶段 12：AI 会话、对话与流式输出

**内容**
- 会话 CRUD、消息落库、短期记忆（Redis，窗口 20）与长期记忆
- 非流式 `/ai/chat`：意图路由 → KB 与图谱并行 → 不足则联网 → 生成 → 引用解析
- 流式 `/ai/chat/stream`：UI Message Stream 协议（§5.5）、工具调用、reasoning 映射、`onFinish` 落库
- 引用 `[n]` 过滤，只返回实际引用来源
- 未配置 Key 时返回 503

**验收**：前端 `useChat` 可正常渲染增量文本、过程状态与来源卡片；刷新后可加载历史消息；会话可重命名/删除。

**提交**：`feat(ai): 实现会话管理与流式问答`

---

### 阶段 13：前端落位与联调

**内容**
- 将 `knowledge-hub-frontend/` 全量复制为 `frontend/`（排除 `node_modules`、`dist`），保持逐字节一致
- 不改 `vite.config.ts`、不改 API 客户端、不改页面
- 补齐后端缺失字段与排序细节，直至所有页面无报错

**验收**
- `npm ci && npm run build` 通过；
- `npm run dev` 后登录、文档列表/详情/编辑、审核、搜索、图谱、AI 对话全流程可用；
- 浏览器控制台无 4xx/5xx（刻意越权场景除外）。

**提交**：`feat(web): 接入前端工程并完成联调`

---

### 阶段 14：测试、文档与交付

**内容**
- 接口契约测试（认证、RBAC、文档状态机、审核、分页）
- 关键错误路径测试（401/403/404/400 结构）
- README：启动顺序、账号、环境变量、常见问题
- 冒烟脚本：一键验证登录 → 创建 → 发布 → 检索 → 对话

**验收**：`uv run pytest` 全绿；`docker compose up -d` + `uvicorn` + `vite` 三步可复现完整环境。

**提交**：`test: 补充接口契约测试与交付文档`

---

## 9. 提交规范

采用 Conventional Commits，类型限定为 `feat / fix / chore / refactor / test / docs / perf`，描述使用中文，聚焦"做了什么"：

```
feat(auth): 实现注册登录与 JWT 令牌刷新
feat(document): 实现文档创建编辑与状态流转
feat(pipeline): 搭建文档处理消息队列与任务分发
```

要求：

- 一个阶段一个提交，提交内不混入无关改动；
- 提交信息、代码注释、README 中禁止出现"复刻/克隆/副本"等字眼；
- 每个提交都必须满足"可启动"，不允许提交半成品导致服务无法运行；
- 提交前执行 `ruff check` 与 `pytest`（阶段 14 起）。

---

## 10. 风险与对策

### 10.1 SSE 协议不一致

`useChat` 对事件类型与字段极敏感。对策：阶段 12 前先逐行核对 `ai-stream.service.ts` 的事件构造；用真实前端联调验证；保留一条最小样例流用于回归。

### 10.2 文档与实现不一致

README 描述"未配置 Embedding Key 时降级为本地哈希向量"，但 `embedding.service.ts` 实际直接抛错，仅查询侧降级为关键词。对策：**以代码行为为准**，实现为"写入时无 Key 抛错并记录失败，查询时无 Key 走关键词检索"。

### 10.3 Pydantic 校验与 NestJS 行为差异

NestJS `ValidationPipe` 返回 400 + `message: string[]`，FastAPI 默认 422 + `detail`。对策：自定义 `RequestValidationError` handler，收集全部字段错误并按现网格式输出。

### 10.4 雪花 ID 精度

JS `Number` 精度不足以承载 64 位 ID。对策：ORM 内部用 `int`，所有响应序列化层强制 `str`，任何查询参数也按字符串接收后再转 `int`。

### 10.5 CORS 与凭证

`*` 与 `credentials` 冲突。对策：动态回显 `Origin`，避免使用通配符。

### 10.6 Mongo 与 PG 双写一致性

先写 Mongo 再写 PG，PG 失败时删除 Mongo 文档；更新正文时 PG 失败不回滚正文但记录告警，避免正文丢失。所有失败路径必须落日志。

### 10.7 中间件不可用时的降级

ES / Neo4j / RabbitMQ 不可用不应导致主流程 500。对策：检索返回空分页、图谱返回空结构、MQ 投递失败仅告警，并保持接口 200。

### 10.8 路由顺序

FastAPI 同样按注册顺序匹配。`/documents/reviews/...`、`/users/me/...`、`/teams/mine`、`/permissions/tree` 必须位于同前缀的 `{id}` 路由之前。

---

## 11. 验证方案

### 11.1 环境

```bash
docker compose up -d
cd backend && uv sync && uv run uvicorn app.main:app --port 3000 --reload
cd frontend && npm ci && npm run dev
```

### 11.2 接口级

- `pytest`：认证、RBAC、文档状态机、审核流、分页与错误结构；
- `httpx` 冒烟：登录 → 创建草稿 → 上传解析 → 发布 → `/search` → `/rag/search` → `/ai/chat/stream`。

### 11.3 端到端

| 场景 | 预期 |
| --- | --- |
| admin 登录 | 进入工作台，侧边栏权限完整 |
| user 创建并提交审核 | 状态 `PendingReview`，审核人待办 +1 |
| reviewer 通过 | 文档 `Published`，列表可见，索引可检索 |
| reviewer 驳回 | 文档回 `Draft`，驳回意见展示 |
| 团队成员查看 | 可见团队文档；非成员 403 |
| AI 对话 | 增量输出、引用来源卡片、会话历史可回看 |
| 检索 | 关键词高亮、分页正确、无结果不报错 |

### 11.4 契约核对

- 用 OpenAPI 导出与前端 `api/index.ts` 逐条比对方法与路径；
- 抽查 10 个响应体，确认字段名、类型、ID 字符串化与现网一致。

---

## 12. 完成定义

1. 前端源码零改动且 `npm run build` 通过；
2. 全部 §7 路由实现并通过冒烟；
3. 三个预置账号可登录，权限与角色一致；
4. 文档全生命周期（创建 → 审核 → 发布 → 检索 → 归档/删除）闭环；
5. 流式对话在前端可正常消费，引用可溯源；
6. 15 个阶段提交齐备，提交信息规范且无禁用字眼；
7. README 可支撑他人从零启动。
