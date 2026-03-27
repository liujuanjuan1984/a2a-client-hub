# a2a-client-hub

`a2a-client-hub` is a self-hosted A2A client hub for teams and individuals who
need one place to manage, invoke, and operate multiple A2A agents across web
and mobile.

It is a client/control plane, not an A2A provider itself.
It is also not an MCP server, MCP registry, or MCP gateway.

## Why this project exists

When A2A adoption grows, teams usually face the same problems:

- Agent endpoints, credentials, and access policies are scattered.
- Session history and operational visibility are fragmented per provider.
- Cross-platform user experience (web/mobile) is inconsistent.
- Calling external A2A endpoints directly creates security and governance risks.

`a2a-client-hub` addresses this by providing a unified frontend + backend system
for agent discovery, invocation, session continuity, scheduling, and controlled
outbound access.

## Ecosystem Positioning

This project is designed for the A2A ecosystem first.

- It aims to work with multiple A2A peer profiles rather than one provider only.
- Current repository examples still use OpenCode-flavored contracts heavily
  because that profile is one of the most fully exercised in this codebase.
- The Hub is not intended to replace MCP. MCP is an agent-internal tool/context
  protocol; this project focuses on agent-to-agent integration and control-plane
  concerns.

Current compatibility framing:

- First-class today: A2A peers that expose standard Agent Cards plus the shared
  session / interrupt capabilities consumed by the Hub.
- Explicitly exercised in this repository: OpenCode-compatible peers and other
  coding-agent peers, including Codex-family deployments, when they publish a
  compatible A2A surface.
- Partial compatibility: standard A2A peers that only support invoke / stream
  without the shared extension workflows used for session continuity.

See [docs/compatibility-and-non-goals.md](docs/compatibility-and-non-goals.md)
for the maintained compatibility notes and explicit non-goals.

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

## Production Parameter Baseline (Scheduler and Streaming)

Set the following parameters explicitly in production to avoid long
transactions and stuck scheduler runs:

- `A2A_SCHEDULE_TASK_INVOKE_TIMEOUT`
  - Total timeout for a single scheduled invoke (the only run-time upper
    bound). It should be higher than your common task duration ceiling.
- `A2A_SCHEDULE_RUN_HEARTBEAT_INTERVAL_SECONDS`
  - Heartbeat update interval during scheduler execution. Recommended:
    15-60 seconds, and it must be lower than invoke timeout.
  - Heartbeat writes use short `lock_timeout/statement_timeout` values so
    lock contention fails fast and retries on the next heartbeat cycle.
- `A2A_SCHEDULE_TASK_STREAM_IDLE_TIMEOUT`
  - Upstream stream idle timeout. Recommended: 30-120 seconds.
- `A2A_SCHEDULE_EXECUTION_RETENTION_DAYS`
  - Retention window for terminal schedule execution history. Recommended:
    14-30 days for small deployments unless you need a longer audit trail.
- PostgreSQL `idle_in_transaction_session_timeout`
  - Set a database-level fallback (for example, 60s-300s) to prevent long
    `idle in transaction` sessions on exceptional paths.
- Cross-process mutual exclusion for the scheduler dispatcher
  - PostgreSQL advisory lock ensures only one process executes the
    dispatch loop at a time, reducing extra contention from multi-instance
    concurrent scan-and-claim behavior.

You can observe these via `/health` under `a2a.ops_metrics`:

- `db_idle_in_tx_count`
- `db_pool_checked_out`
- `schedule_running_task_count`
- `schedule_run_finalize_latency`

## Key docs

- Documentation index: [docs/README.md](docs/README.md)
- Contributor guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Automation protocol: [AGENTS.md](AGENTS.md)
- Backend details: [backend/README.md](backend/README.md)
- Frontend details: [frontend/README.md](frontend/README.md)
- Authentication conventions: [docs/authentication.md](docs/authentication.md)
- Production security baseline: [docs/security-baseline.md](docs/security-baseline.md)
- Release automation: [docs/release-workflow.md](docs/release-workflow.md)
- Shared session query contract:
  [docs/contracts/shared-session-query-canonical-contract.md](docs/contracts/shared-session-query-canonical-contract.md)
- Architecture and API examples:
  [docs/architecture-and-api.md](docs/architecture-and-api.md)
- Compatibility notes and non-goals:
  [docs/compatibility-and-non-goals.md](docs/compatibility-and-non-goals.md)

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
