# knowledge-hub-frontend

对接 `knowledge-hub-backend` 的 React 管理台（Vite + Ant Design）。

## 本地运行

后端先起在 `http://localhost:3000`。

```bash
cd knowledge-hub-frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。开发时 `/api` 会代理到 3000。

预置账号：`user` / `123456`（文档与检索），`admin` / `123456`（系统管理），`reviewer` / `123456`（审核）。

## 已对接

- 登录 / 资料 / 改密
- 文档列表、新建、编辑、发布、归档、下架、删除、上传解析
- 全文搜索 `POST /search`
- RAG 问答 `POST /ai/chat`、仅检索 `POST /rag/search`
- 图谱检索 / 实体 / 关系
- 用户、角色权限、团队、审核工作台
