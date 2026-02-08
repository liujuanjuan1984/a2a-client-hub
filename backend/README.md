# a2a-client-hub (backend)

该目录包含 FastAPI 后端代码与迁移脚本（Alembic）。

## 本地运行（开发）

```bash
cd backend
uv sync --extra dev --locked
```

创建并配置 `backend/.env`（参考 `backend/.env.example`）。

初始化 schema 并执行迁移：

```bash
cd backend

# 需要先配置 RS256 key（见 backend/.env.example），否则会报错并提示如何生成。
uv run python scripts/setup_db_schema.py --create

uv run alembic upgrade head
```

启动服务：

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 回归

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
