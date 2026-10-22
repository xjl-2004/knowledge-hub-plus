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

## 目录说明

```
backend/    FastAPI 服务
frontend/   前端工程
init-scripts/   PostgreSQL / MongoDB 初始化脚本
deploy/     Elasticsearch 镜像构建
```
