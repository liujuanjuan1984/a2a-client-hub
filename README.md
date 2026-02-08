# a2a-client-backend

本仓库是 `a2a-client-mobile` 的后端服务（FastAPI + PostgreSQL）。当前处于从 `common_compass_dev` 拆分迁入并“删除式裁剪”的阶段：技术栈与数据协议保持不变，仅做模块切割与冗余移除。

## 本地运行（开发）

1. 安装依赖（使用 `uv`）：

```bash
cd backend
uv sync --extra dev --locked
```

2. 配置环境变量：

- 参考 `backend/.env.example`，创建 `backend/.env`
- 至少需要：`DATABASE_URL`、`SCHEMA_NAME`、JWT 相关配置

3. 初始化 schema 并执行迁移：

```bash
cd backend

# 需要先配置 RS256 key（见 backend/.env.example），否则会报错并提示如何生成。
uv run python ../scripts/setup_db_schema.py --create

uv run alembic upgrade head
```

4. 启动服务：

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

默认 API 前缀为 `/api/v1`（见 `API_V1_PREFIX`）。

## 回归（提交前必须通过）

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
