# a2a-client-hub

`a2a-client-hub` is a self-hosted A2A client hub for teams and individuals who
need one place to manage, invoke, and operate multiple A2A agents across web
and mobile.

It is a client/control plane, not an A2A provider itself.

## Why this project exists

When A2A adoption grows, teams usually face the same problems:

- Agent endpoints, credentials, and access policies are scattered.
- Session history and operational visibility are fragmented per provider.
- Cross-platform user experience (web/mobile) is inconsistent.
- Calling external A2A endpoints directly creates security and governance risks.

`a2a-client-hub` addresses this by providing a unified frontend + backend system
for agent discovery, invocation, session continuity, scheduling, and controlled
outbound access.

## What value it delivers

- Faster integration: connect multiple A2A agents from one product surface.
- Better governance: enforce allowlists, admin-only control, and secure
  token handling.
- Better user continuity: keep chat and session flows available across devices.
- Better extensibility: support A2A extension workflows (for example, OpenCode
  session query) without tightly coupling to provider-specific schemas.

## Core capabilities

- Personal A2A agent management
  - Add, validate, update, and remove user-managed agents.
  - Invoke via HTTP and WebSocket.
- Admin-managed Hub Catalog
  - Publish global agents for all users (`public`) or selected users
    (`allowlist`).
  - Keep admin credentials encrypted and hidden from normal users.
- Session and chat continuity
  - Persist sessions/messages and query them from user-facing APIs.
  - Continue existing upstream sessions in the same chat UI flow.
- Scheduled invocation
  - Create and manage recurring A2A schedule tasks.
  - Support both anchor-based `interval` and completion-based `sequential` modes.
  - Track execution history for operational visibility.
- Security controls
  - Outbound A2A host allowlist enforcement.
  - Short-lived access token + rotating HttpOnly refresh cookie model.
  - WebSocket one-time ticket flow and origin validation.

## Architecture at a glance

- `frontend/`
  - Expo + React Native + Web client
  - Auth, catalog browsing, chat/session UI, schedule UI, admin screens
- `backend/`
  - FastAPI + PostgreSQL + Alembic
  - Auth, agent orchestration, scheduling, A2A proxy/runtime, persistence
- `docs/`
  - Cross-cutting architecture and API examples

See [docs/architecture-and-api.md](docs/architecture-and-api.md) for request
flows and endpoint examples.

## Quick start (local development)

### Prerequisites

- Python 3.12+
- Node.js 18+
- PostgreSQL
- `uv` (Python package manager)

### 1. Start backend

```bash
cd backend
uv sync --extra dev --locked
cp .env.example .env
uv run python scripts/setup_db_schema.py --create
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Notes:

- RS256 JWT keys are required. Configure them in `backend/.env` based on
  `backend/.env.example`.
- Configure `A2A_PROXY_ALLOWED_HOSTS` before invoking downstream A2A endpoints.

### 2. Start frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run start
```

Set `EXPO_PUBLIC_API_BASE_URL` in `frontend/.env` for your backend.

## 生产参数基线（调度与流式）

以下参数建议在生产环境显式配置，用于避免长事务与调度悬挂：

- `A2A_SCHEDULE_RUN_LEASE_SECONDS`
  - 调度运行 lease 超时（恢复扫描依据），建议 900~3600 秒。
- `A2A_SCHEDULE_TASK_INVOKE_TIMEOUT`
  - 单次调度 invoke 的总超时（与 lease 解耦），建议大于常见任务耗时上界。
- `A2A_SCHEDULE_TASK_STREAM_IDLE_TIMEOUT`
  - 上游流空闲超时，建议 30~120 秒。
- PostgreSQL `idle_in_transaction_session_timeout`
  - 建议在数据库层设置（例如 60s~300s）作为兜底保护，防止异常路径长时间 `idle in transaction`。

可在 `/health` 的 `a2a.ops_metrics` 里观察：

- `db_idle_in_tx_count`
- `db_pool_checked_out`
- `schedule_running_task_count`
- `schedule_run_finalize_latency`

## Key docs

- Contributor guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Automation protocol: [AGENTS.md](AGENTS.md)
- Backend details: [backend/README.md](backend/README.md)
- Frontend details: [frontend/README.md](frontend/README.md)
- Authentication conventions: [docs/authentication.md](docs/authentication.md)
- Production security baseline: [docs/security-baseline.md](docs/security-baseline.md)
- Architecture and API examples:
  [docs/architecture-and-api.md](docs/architecture-and-api.md)

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
