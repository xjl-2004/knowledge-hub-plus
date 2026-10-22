# Knowledge Hub Plus

企业知识库系统，覆盖文档全生命周期管理、审核流转、权限与团队、全文/向量混合检索、知识图谱和 Agentic RAG 问答。

后端基于 Python + FastAPI，前端为 React 19 + Vite 8 + Ant Design 6。所有接口统一返回 camelCase 字段，错误统一为 `{ "message": "..." }` 或 `{ "message": ["..."] }`。

## 功能特性

### 文档中心

- 文档创建、编辑、保存草稿、发布、归档、删除。
- 上传解析：支持 `pdf`、`docx`、`xlsx`、`pptx`、`txt`、`md`，自动提取文本；PDF 内嵌图片会抽取并上传到对象存储。
- 正文存储：元数据保存在 PostgreSQL，正文保存在 MongoDB `document_content`。
- 自动生成摘要、字数统计、标签、分类、所属团队。
- 可见性控制：公开文档、团队文档、作者本人文档按规则组合可见。

### 审核流转

- 审核开关 `DOCUMENT_REQUIRE_APPROVAL` 控制发布是否进入审核。
- 审核任务列表、待审数量、通过、驳回、当前审核与历史记录。
- 驳回后回到草稿，审核通过后自动发布并触发知识管线。

### 检索

- 文档级全文检索：Elasticsearch `kh_document`，IK 中文分词，带权限过滤。
- 分块级混合检索：`kh_chunk` 同时执行 BM25 关键词召回与 1024 维向量 kNN 召回，RRF 融合后重排。
- 检索结果始终按“公开 ∪ 本人 ∪ 所在团队”过滤，越权内容不会出现在召回与引用中。

### 知识图谱

- 发布文档后异步抽取实体与关系，写入 Neo4j。
- 图结构：`KnowledgeDocument -HAS_CHUNK-> DocumentChunk -MENTIONS-> KnowledgeEntity -RELATED_TO-> KnowledgeEntity`。
- 提供图谱总览、关键词搜索、节点列表、边列表，以及供问答使用的图谱召回。

### AI 问答

- 会话列表、自动标题、消息落库、重命名、删除。
- 短期记忆存 Redis，长期记忆可选接入 Mem0。
- Agentic RAG：模型自主调用知识库检索、检索词改写、图谱检索、联网搜索四类工具，生成带 `[n]` 引用的回答。
- 流式输出兼容 AI SDK UI Message Stream v1，前端可直接使用 `useChat` 消费。
- 未配置模型 Key 时，文档管理与检索不受影响，问答接口返回 503。

### 权限与组织

- RBAC：用户 → 角色 → 权限，支持用户级权限覆盖。
- 预置角色：`ROLE_ADMIN`、`ROLE_REVIEWER`、`ROLE_USER`。
- 团队树与成员管理，团队用于文档可见性判断。
- JWT 双令牌：访问令牌 `2h`，刷新令牌 `7d`，前端在 401 时自动刷新并重放请求。

## 技术架构

| 组件 | 技术 | 默认端口 | 用途 |
| --- | --- | --- | --- |
| 后端 | Python 3.12+ / FastAPI / SQLAlchemy 2.x async | 3000 | API、SSE、异步管线编排 |
| 前端 | React 19 / Vite 8 / Ant Design 6 / ECharts | 5173 | 管理界面与问答界面 |
| PostgreSQL | pgvector/pg16 | 5432 | 用户、角色、权限、团队、文档元数据、审核、AI 会话 |
| MongoDB | mongo:7 | 27017 | 文档正文 |
| Redis | redis:7 | 6379 | 短期对话记忆、验证码 |
| RabbitMQ | rabbitmq:3.13-management | 5672 / 15672 | 发布后异步任务 |
| Elasticsearch | 8.17 + IK 分词 | 9200 | 文档全文索引、分块混合索引 |
| Neo4j | 2026.04 + APOC | 7474 / 7687 | 知识图谱 |
| RustFS | S3 兼容对象存储 | 9000 / 9001 | 原文件、PDF 抽图 |
| pgAdmin | dpage/pgadmin4 | 8088 | PostgreSQL 控制台 |
| mongo-express | mongo-express | 8081 | MongoDB 控制台 |
| RedisInsight | redis/redisinsight | 5540 | Redis 控制台 |
| Kibana | kibana:8.17.0 | 5601 | Elasticsearch 控制台 |

```text
浏览器 / React SPA
        │  /api/*（Vite 开发代理，剥离 /api 前缀）
        ▼
   FastAPI :3000
        ├── PostgreSQL    用户、权限、团队、文档元数据、审核、会话
        ├── MongoDB       文档正文
        ├── Redis         短期对话记忆
        ├── RustFS        原文件与 PDF 图片
        ├── RabbitMQ ──►  kh.rag.reindex.queue   分块 + 向量化 → kh_chunk
        │              kh.search.index.queue  文档索引 → kh_document
        │              kh.kg.graph.queue      图谱构建 → Neo4j
        ├── Elasticsearch 全文检索 / BM25 + kNN + RRF
        ├── Neo4j         实体关系图谱
        └── DashScope     embedding / qwen-plus / qwen3-rerank
```

后端不暴露 `/api` 前缀。前端所有请求以 `/api` 开头，由 Vite 开发代理或生产反向代理剥离后转发到 3000 端口。

## 文档生命周期

| 状态 | 值 | 说明 |
| --- | --- | --- |
| 草稿 | `0` | 创建后的默认状态，可编辑、可发布 |
| 已发布 | `1` | 对外可见，进入检索与图谱 |
| 已归档 | `2` | 不再对外展示，可重新发布 |
| 待审核 | `3` | 审核中，不可编辑正文 |

```text
新建 ──► 草稿(0) ──发布──► 已发布(1) ──归档──► 已归档(2)
            │                   ▲                  │
            │                   │                  └──重新发布──┐
            └─提交审核─► 待审核(3) ─通过─┘                        │
                              │                                  │
                              └─驳回─► 草稿(0) ◄─────────────────┘（重新发布触发审核）
```

- `DOCUMENT_REQUIRE_APPROVAL=true` 时，草稿或已发布文档执行“发布”会转入待审核；归档文档重新发布则直接生效。
- 审核通过：状态置为已发布，写 `publishTime`，并触发异步管线。
- 审核驳回：状态回到草稿，驳回意见必填。

## 发布后异步管线

文档发布后写入 RabbitMQ，三类队列相互独立、失败互不影响：

| 交换机 | 队列 | 路由键 | 处理内容 |
| --- | --- | --- | --- |
| `rag.reindex.exchange` | `kh.rag.reindex.queue` | `rag.reindex.by_ids` / `rag.reindex.delete` | 读取正文 → 分块 → 向量化 → 写入 `kh_chunk` |
| `search.index.exchange` | `kh.search.index.queue` | `search.index.document` / `search.index.delete` | 写入/删除 `kh_document` 全文索引 |
| `kg.graph.exchange` | `kh.kg.graph.queue` | `kg.graph.build.by_ids` / `kg.graph.delete` | 实体关系抽取 → 写入 Neo4j |

文档删除、下架会发送对应的 `delete` 路由键清理索引与图谱。

分块参数：`RAG_CHUNK_SIZE=512`、`RAG_CHUNK_OVERLAP=64`；分块 ID 为 `sha256("{documentId}:{index}")[:64]`，保证重复处理幂等。

## 检索与问答链路

### 分块混合检索

1. 查询文本向量化（`EMBEDDING_MODEL`，默认 `text-embedding-v3`，1024 维）。
2. `kh_chunk` 并行执行关键词查询与 `knn` 向量查询，各取 `RAG_HYBRID_TOP_K` 条。
3. 使用 RRF 融合，参数 `RAG_RRF_C=60`。
4. 开启 `RAG_RERANK_ENABLED` 时调用 `qwen3-rerank` 重排，低于 `RAG_MIN_SCORE` 的结果丢弃。
5. 返回前 `topK` 条，字段包含 `chunkId`、`documentId`、`documentTitle`、`content`、`score` 等。

### Agentic RAG

问答不是固定“检索一次再回答”，而是由模型按需调用工具，最多 8 轮模型调用：

| 工具 | 作用 |
| --- | --- |
| `retrieve_knowledge` | 知识库混合检索，每次回答最多调用 2 次 |
| `rewrite_query` | 检索不足时改写查询词 |
| `retrieve_graph` | 图谱实体关系召回，必须与首次知识库检索并行调用 |
| `web_search` | 博查联网搜索，仅在知识库两次仍不足时使用 |

模型输出通过 UI Message Stream 返回，前端消费的事件包括：

| 事件 | 说明 |
| --- | --- |
| `start` / `start-step` / `finish-step` / `finish` | 消息与步骤生命周期 |
| `text-start` / `text-delta` / `text-end` | 正文增量 |
| `reasoning-start` / `reasoning-delta` / `reasoning-end` | 思考过程（`LLM_ENABLE_THINKING=true` 时） |
| `tool-input-start` / `tool-input-available` / `tool-output-available` / `tool-output-error` | 工具调用过程 |
| `source-document` | 单条引用来源 |
| `data-session` / `data-status` / `data-intent` / `data-eval` / `data-sources` / `data-graph` | 会话、阶段状态、意图、检索评估、来源列表、图谱命中 |

响应头包含 `x-vercel-ai-ui-message-stream: v1`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`，最后以 `data: [DONE]` 结束。

## 目录结构

```text
knowledge-hub-plus/
├── backend/
│   ├── app/
│   │   ├── ai/            会话、短期/长期记忆、意图路由、Agentic 编排、SSE 编码
│   │   ├── core/          配置、鉴权依赖、异常、日志、雪花 ID、安全
│   │   ├── db/            PostgreSQL / MongoDB / Redis / ES / Neo4j / S3 连接
│   │   ├── integrations/  重排、邮件
│   │   ├── models/        SQLAlchemy 实体
│   │   ├── mq/            RabbitMQ 拓扑、发布、消费
│   │   ├── pipeline/      分块、向量化、索引、图谱构建、可见性、管线编排
│   │   ├── routers/       auth / users / roles / permissions / teams / documents / search / graph / ai
│   │   ├── schemas/       Pydantic 入参与出参
│   │   ├── services/      账号、认证、文档、审核、解析、检索
│   │   └── main.py        应用入口与生命周期
│   ├── tests/             接口契约与业务规则测试
│   ├── pyproject.toml
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/           fetch 封装、自动刷新令牌、接口定义
│   │   ├── components/    聊天消息、引用列表、图谱、文件图标
│   │   ├── layouts/       侧边栏布局
│   │   ├── pages/         登录、首页、文档、搜索、图谱、问答、个人中心、系统管理
│   │   ├── auth.ts        令牌存取
│   │   ├── types.ts       前端类型
│   │   └── App.tsx        路由
│   └── vite.config.ts
├── scripts/smoke.py       冒烟脚本
├── init-scripts/          PostgreSQL / MongoDB 初始化脚本
├── deploy/elasticsearch/  带 IK 分词的 ES 镜像
├── docker-compose.yml
└── plan.md
```

## 快速开始

### 前置条件

- Docker Desktop 或兼容的容器运行时。
- Python 3.12+（推荐 3.12 / 3.13）。
- Node.js 20.19+ 或 22.12+（Vite 8 要求）与 npm。

### 1. 启动中间件

```bash
docker compose up -d
```

首次启动会拉取镜像并构建带 IK 的 Elasticsearch，耗时较长。只启动核心依赖可使用：

```bash
docker compose up -d postgres mongodb redis rabbitmq es rustfs neo4j
```

各控制台入口：

| 服务 | 地址 | 账号 |
| --- | --- | --- |
| RabbitMQ | http://localhost:15672 | guest / guest |
| Kibana | http://localhost:5601 | 无 |
| Neo4j Browser | http://localhost:7474 | neo4j / 12345678 |
| RustFS Console | http://localhost:9001 | rustfsadmin / rustfsadmin |
| pgAdmin | http://localhost:8088 | admin@admin.com / admin |
| mongo-express | http://localhost:8081 | me_admin / me_123456 |
| RedisInsight | http://localhost:5540 | 无 |

### 2. 启动后端

使用 uv：

```bash
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

或使用 venv + pip：

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload
```

Windows PowerShell 下将 `cp .env.example .env` 替换为 `Copy-Item .env.example .env`，激活脚本替换为 `.venv\Scripts\Activate.ps1`。

`.env.example` 中的 `OPENAI_API_KEY=sk-xxx` 是占位值。没有可用 Key 时请改为空字符串，否则会被当作已配置。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 。前端默认请求 `/api`，由 Vite 代理到 `http://127.0.0.1:3000` 并剥离 `/api`。

### 4. 验证服务

```bash
curl http://127.0.0.1:3000/health
curl http://127.0.0.1:3000/
```

接口文档：http://127.0.0.1:3000/docs 。

## 预置账号与权限

| 用户名 | 密码 | 角色 | 说明 |
| --- | --- | --- | --- |
| admin | 123456 | ROLE_ADMIN + ROLE_REVIEWER | 全部权限 |
| reviewer | 123456 | ROLE_REVIEWER | 文档列表、审核、搜索 |
| user | 123456 | ROLE_USER | 文档创建/编辑/删除、搜索、个人中心 |

权限编码：

| 权限 | 编码 |
| --- | --- |
| 首页 | `dashboard` |
| 文档中心 | `document` |
| 文档列表 | `document:list` |
| 创建文档 | `document:create` |
| 编辑文档 | `document:edit` |
| 删除文档 | `document:delete` |
| 文档审核 | `document:review` |
| 搜索 | `search` |
| 个人中心 | `profile` |
| 系统管理 | `system` |
| 用户管理 | `system:user` |
| 角色管理 | `system:role` |
| 权限管理 | `system:permission` |
| 团队管理 | `system:team` |

只读接口在列表查询时会做可见性过滤；写操作还会额外校验作者身份。管理员与审核员判断基于角色编码，避免仅靠权限编码误放行。

## 环境变量

配置文件位于 `backend/.env`，全部变量见 `backend/.env.example`。常用项如下。

### 基础

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `3000` | 配置项；uvicorn 启动命令仍需显式传入 `--port` |
| `DEBUG` | `false` | 调试日志 |
| `APP_PUBLIC_URL` | `http://localhost:3000` | 邮件链接等外部地址 |
| `JWT_SECRET` | `dev-secret-change-me-in-production` | 生产必须替换 |
| `JWT_ACCESS_EXPIRES` | `2h` | 访问令牌有效期 |
| `JWT_REFRESH_EXPIRES` | `7d` | 刷新令牌有效期 |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | 注册是否要求邮箱验证 |

### 数据存储

| 变量 | 默认值 |
| --- | --- |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `localhost` / `5432` / `user` / `123456` / `knowledge_hub` |
| `MONGO_URI` / `MONGO_DB` | `mongodb://mongo_user:mongo_pass123@localhost:27017/knowledge_hub?authSource=admin` / `knowledge_hub` |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` | `localhost` / `6379` / 空 / `0` |
| `ELASTICSEARCH_ENABLED` / `ELASTICSEARCH_NODE` | `true` / `http://localhost:9200` |
| `NEO4J_ENABLED` / `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | `true` / `bolt://localhost:7687` / `neo4j` / `12345678` |
| `RABBITMQ_ENABLED` / `RABBITMQ_URL` | `true` / `amqp://guest:guest@localhost:5672` |
| `RUSTFS_ENABLED` / `RUSTFS_ENDPOINT` / `RUSTFS_BUCKET` | `true` / `http://localhost:9000` / `knowledge-hub` |

### 检索与模型

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `RAG_CHUNK_SIZE` / `RAG_CHUNK_OVERLAP` | `512` / `64` | 分块大小与重叠 |
| `EMBEDDING_DIMENSION` | `1024` | 必须与索引 mapping 一致 |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | DashScope 兼容地址 / `text-embedding-v3` | 向量模型 |
| `EMBEDDING_API_KEY` / `DASHSCOPE_API_KEY` | 空 | 向量化 Key，兼容读取 |
| `RAG_HYBRID_TOP_K` | `20` | 每路召回条数 |
| `RAG_RRF_C` | `60` | RRF 常数 |
| `RAG_RERANK_ENABLED` / `RAG_RERANK_MODEL` | `true` / `qwen3-rerank` | 重排开关与模型 |
| `RAG_MIN_SCORE` | `0.4` | 重排最低分 |
| `RERANK_API_KEY` / `RERANK_BASE_URL` | 空 / DashScope | 重排服务 |
| `OPENAI_API_KEY` / `LLM_API_KEY` | 空 | 对话模型 Key，按顺序取第一个非空值 |
| `OPENAI_BASE_URL` / `MODEL_NAME` | DashScope 兼容地址 / `qwen-plus` | 对话模型 |
| `LLM_ENABLE_THINKING` | `true` | 是否输出思考过程 |
| `AI_CHAT_TIMEOUT_MS` | `60000` | 非流式问答超时 |
| `AI_QUERY_REWRITE_TIMEOUT_MS` | `15000` | 意图与改写超时 |
| `KG_LLM_TIMEOUT_MS` | `120000` | 图谱抽取超时 |
| `KG_MAX_ENTITIES` / `KG_MAX_RELATIONS` | `12` / `15` | 单文档抽取上限 |
| `BOCHA_API_KEY` | 空 | 联网搜索 |

### 会话记忆与审核

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CHAT_SHORT_MEMORY_TTL_SECONDS` | `86400` | 短期记忆过期时间 |
| `CHAT_SHORT_MEMORY_MAX_MESSAGES` | `20` | 上下文窗口消息数 |
| `CHAT_SHORT_MEMORY_KEY_PREFIX` | `kh:chat` | Redis 键前缀 |
| `MEM0_API_KEY` / `MEM0_HOST` / `MEM0_TOP_K` | 空 / `https://api.mem0.ai` / `5` | 长期记忆，未配置时自动跳过 |
| `DOCUMENT_REQUIRE_APPROVAL` | `true` | 发布是否进入审核 |
| `MAIL_HOST` / `MAIL_PORT` / `MAIL_USER` / `MAIL_PASS` / `MAIL_FROM` | 见示例 | 邮件验证与重置密码 |

## API 概览

完整定义以 `/docs` 为准。所有字段为 camelCase，ID 统一为字符串。

| 模块 | 方法与路径 | 说明 |
| --- | --- | --- |
| 认证 | `POST /auth/register` | 注册 |
| | `POST /auth/login` | 登录，返回 `accessToken` / `refreshToken` / `userInfo` |
| | `POST /auth/refresh` | 刷新令牌 |
| | `GET /auth/me` | 当前用户 |
| | `POST /auth/logout` | 退出 |
| | `POST /auth/password/reset/send-code` | 发送重置验证码 |
| | `POST /auth/password/reset` | 通过验证码重置密码 |
| | `GET /auth/verify-email` | 邮箱验证 |
| 文档 | `GET /documents` | 分页查询，按可见性过滤 |
| | `POST /documents` | 创建 |
| | `GET /documents/{id}` | 详情（含正文） |
| | `PATCH /documents/{id}` | 更新 |
| | `DELETE /documents/{id}` | 删除并清理索引 |
| | `PUT /documents/{id}/publish` | 发布或提交审核 |
| | `PUT /documents/{id}/archive` | 归档 |
| | `PUT /documents/{id}/save-draft` | 撤回为草稿 |
| | `POST /documents/upload/parse` | 上传并解析文件 |
| 审核 | `GET /documents/reviews/tasks` | 审核任务分页 |
| | `GET /documents/reviews/tasks/pending-count` | 待审数量 |
| | `POST /documents/reviews/tasks/{id}/approve` | 通过 |
| | `POST /documents/reviews/tasks/{id}/reject` | 驳回 |
| | `POST /documents/{id}/reviews/submit` | 主动提交审核 |
| | `GET /documents/{id}/reviews/current` / `history` | 当前审核 / 历史 |
| 搜索 | `POST /search` | 文档全文检索 |
| | `POST /rag/search` | 分块混合检索 |
| 图谱 | `GET /graph/overview` | 总览（节点 + 边） |
| | `GET /graph/search` | 关键词命中的图节点 |
| | `GET /graph/nodes` / `GET /graph/edges` | 节点 / 边列表 |
| AI | `POST /ai/chat` | 非流式问答 |
| | `POST /ai/chat/stream` | 流式问答（SSE） |
| | `GET /ai/sessions` / `POST /ai/sessions` | 会话分页 / 新建 |
| | `GET /ai/sessions/{id}/messages` | 消息列表 |
| | `PATCH /ai/sessions/{id}` / `DELETE /ai/sessions/{id}` | 重命名 / 删除 |
| 用户 | `GET /users/me/stats` / `PUT /users/me` | 个人统计 / 资料 |
| | `PUT /users/password/change` | 修改密码 |
| | `GET /users/page` 等 | 用户管理（管理员） |
| 角色 | `GET /roles/list` 等 | 角色管理与授权（管理员） |
| 权限 | `GET /permissions/tree` / `list` / `page` | 权限树与列表（管理员） |
| 团队 | `GET /teams/tree` / `mine` / `page` | 团队树、我的团队、分页 |
| | `POST /teams/{id}/members` 等 | 成员维护（管理员） |

## 前端说明

| 路由 | 页面 | 说明 |
| --- | --- | --- |
| `/login` | 登录 | 账号密码登录，保存双令牌 |
| `/dashboard` | 首页 | 数据概览 |
| `/documents` | 文档中心 | 列表、筛选、上传、发布 |
| `/documents/new` | 新建文档 | 需要 `document:create` |
| `/documents/:id` | 文档详情 | 正文、审核状态、操作 |
| `/documents/:id/edit` | 文档编辑 | 新建与编辑共用 |
| `/search` | 搜索 | 全文检索与结果高亮 |
| `/graph` | 知识图谱 | 关系图浏览与搜索 |
| `/chat` | AI 问答 | 会话侧栏、流式回答、引用与工具过程 |
| `/profile` | 个人中心 | 资料、密码、统计 |
| `/admin/users` `/admin/roles` `/admin/teams` `/admin/reviews` | 系统管理 | 按权限展示 |

- 令牌保存在浏览器，请求头自动携带 `Authorization: Bearer <token>`。
- 401 时使用刷新令牌重放请求；刷新失败清除登录态。
- 前端接口字段全部为 camelCase，与后端返回结构一一对应。

## 测试与冒烟

```bash
cd backend
python -m pytest -q
```

测试覆盖：

- 认证错误结构：401、参数校验 400、未知路由 404。
- RBAC：缺少权限 403、缺少角色 403。
- 文档状态机与可见性：发布、编辑、归档、审核流转、公开/团队/作者规则。
- 分页：camelCase 入参、范围校验、统一返回结构。

冒烟脚本在后端与中间件启动后执行：

```bash
python scripts/smoke.py
```

流程为：登录 → 创建文档 → 发布（必要时走审核）→ 全文检索 → 非流式问答 → 清理。

可用环境变量：`SMOKE_BASE_URL`、`SMOKE_USERNAME`、`SMOKE_PASSWORD`。

## 运维与排障

### 常用检查

```bash
# 健康检查
curl http://127.0.0.1:3000/health

# 容器状态
docker compose ps

# 后端日志（本地运行时直接看控制台）
docker compose logs -f rabbitmq es neo4j
```

### 索引重建

索引不存在或 mapping 变更时，删除旧索引后重启后端会自动创建：

```bash
curl -X DELETE http://127.0.0.1:9200/kh_document
curl -X DELETE http://127.0.0.1:9200/kh_chunk
```

随后重新发布文档，或重新发送对应队列消息，即可回填数据。

### 跳过依赖

本地只调试某一部分时，可在 `backend/.env` 关闭对应能力，服务仍可启动：

```env
RABBITMQ_ENABLED=false
ELASTICSEARCH_ENABLED=false
NEO4J_ENABLED=false
RUSTFS_ENABLED=false
```

关闭后相关接口会降级返回空结果或提示，不影响用户、文档元数据等基础功能。

### 常见问题

| 现象 | 排查方向 |
| --- | --- |
| 登录 401 或刷新失效 | 检查 `JWT_SECRET` 是否变更、令牌是否过期、系统时间是否正确 |
| 创建文档 403 | 当前账号缺少 `document:create`，或角色分配未生效 |
| 搜索无结果 | 文档是否已发布、`kh_document` 是否创建、RabbitMQ 消费是否正常、账号是否有可见权限 |
| 图谱为空 | `NEO4J_ENABLED` 是否为 `true`、文档是否发布成功、抽取是否因模型 Key 缺失而失败 |
| 问答返回 503 | 未配置 `OPENAI_API_KEY` / `LLM_API_KEY` / `DASHSCOPE_API_KEY` |
| 流式回答一次性出现 | 反向代理缓冲未关闭，确认 `proxy_buffering off`，后端已发送 `X-Accel-Buffering: no` |
| 中文检索效果差 | ES 镜像是否带 IK 分词，是否使用 `deploy/elasticsearch` 构建 |
| 上传解析失败 | 文件扩展名是否在支持列表内，PDF 是否为可提取文本的版本 |
| 端口冲突 | 修改启动命令的 `--port` 与 `frontend/vite.config.ts` 的代理目标，两者需保持一致 |

## 生产部署建议

- 替换 `JWT_SECRET`，关闭 `DEBUG`，收紧 CORS 白名单（当前中间件为便于开发允许所有来源）。
- 使用 Nginx / 网关统一反向代理：`/api` 转发到后端并去掉前缀，同时关闭 SSE 缓冲。
- PostgreSQL、MongoDB、Elasticsearch、Neo4j、RustFS 配置独立账号与强密码，并限制公网访问。
- 为 RabbitMQ 配置持久化与死信队列，消费端按需水平扩展；多实例部署时确保 `SNOWFLAKE_WORKER_ID` 唯一。
- 定期备份 PostgreSQL、MongoDB、Neo4j 数据卷与对象存储桶。
- 生产环境建议关闭 `/docs`，或在网关层限制访问。
- 高并发场景下调整 `backend/app/db/session.py` 的连接池参数，并监控 Elasticsearch 与模型服务的限流。
