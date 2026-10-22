# Knowledge Hub Plus

企业知识库系统：文档管理、审核流转、全文/向量混合检索、知识图谱与 Agentic RAG 问答。

## 架构

| 模块 | 技术栈 | 端口 |
| --- | --- | --- |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.x | 3000 |
| 前端 | React 19 + Vite 8 + Ant Design 6 | 5173 |
| PostgreSQL | pgvector/pg16 | 5432 |
| MongoDB | mongo:7 | 27017 |
| Redis | redis:7 | 6379 |
| RabbitMQ | rabbitmq:3-management | 5672 / 15672 |
| Elasticsearch | 8.17（含 IK 分词） | 9200 |
| Kibana | 8.17 | 5601 |
| RustFS | S3 兼容对象存储 | 9000 / 9001 |
| Neo4j | 2026.04 | 7474 / 7687 |

## 快速开始

```bash
# 1. 启动中间件
docker compose up -d

# 2. 启动后端
cd backend
uv sync
cp .env.example .env
uv run uvicorn app.main:app --host 0.0.0.0 --port 3000 --reload

# 3. 启动前端
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 。

## 预置账号

| 用户名 | 密码 | 角色 |
| --- | --- | --- |
| admin | 123456 | 管理员 + 审核员 |
| reviewer | 123456 | 审核员 |
| user | 123456 | 普通用户 |

## 环境变量

见 `backend/.env.example`。未配置 LLM Key 时，文档管理与检索仍可用，AI 问答返回 503。

关键项：

- `OPENAI_API_KEY` / `LLM_API_KEY` / `DASHSCOPE_API_KEY`：对话与结构化输出，缺省时相关能力降级。
- `EMBEDDING_API_KEY` / `DASHSCOPE_API_KEY`：向量化；未配置时写入失败并记录日志，查询仅走关键词。
- `BOCHA_API_KEY`：联网搜索工具，缺省时工具返回提示信息。
- `RABBITMQ_ENABLED` / `ELASTICSEARCH_ENABLED` / `NEO4J_ENABLED` / `RUSTFS_ENABLED`：本地调试可置为 `false` 跳过对应中间件。

## 测试与冒烟

```bash
cd backend
python -m pytest -q

# 后端与中间件启动后，验证登录 → 创建 → 发布 → 检索 → 对话
python ../scripts/smoke.py
```

冒烟脚本默认使用 `admin / 123456` 访问 `http://127.0.0.1:3000`，可通过 `SMOKE_BASE_URL`、`SMOKE_USERNAME`、`SMOKE_PASSWORD` 覆盖。

## 常见问题

- 前端请求统一带 `/api` 前缀，由 Vite 代理剥离；后端监听 3000 且路由本身不含 `/api`。
- 流式问答依赖 SSE，反向代理需关闭缓冲；后端已返回 `X-Accel-Buffering: no`，Nginx 侧仍需确认 `proxy_buffering off`。
- 审核开关 `DOCUMENT_REQUIRE_APPROVAL=true` 时，发布动作先进入待审核；审核通过后才置为已发布。
- 端口冲突时修改 `backend/.env` 的 `PORT` 与 `frontend/vite.config.ts` 的代理目标，两者需保持一致。

## 目录说明

```
backend/    FastAPI 服务
frontend/   前端工程
scripts/    冒烟与运维脚本
init-scripts/   PostgreSQL / MongoDB 初始化脚本
deploy/     Elasticsearch 镜像构建
```
