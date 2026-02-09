# a2a-client-hub (backend)

FastAPI backend for **a2a-client-hub** (PostgreSQL + Alembic).

## Local Development

Install dependencies (via `uv`):

```bash
cd backend
uv sync --extra dev --locked
```

Create `backend/.env` (see `backend/.env.example`).

## Initialize Schema and Run Migrations

```bash
cd backend

# RS256 keys are required (see backend/.env.example). The backend will error if missing.
uv run python scripts/setup_db_schema.py --create

uv run alembic upgrade head
```

Notes:

- `alembic.ini` contains a placeholder `sqlalchemy.url`. Alembic uses `DATABASE_URL` via `app.core.config.Settings`.
- The schema name is **fixed** to `a2a_client_hub_schema` (tests use `test_a2a_client_hub_schema`). Custom `SCHEMA_NAME` values are not supported.

## Run the Server

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Default API prefix: `/api/v1`.

## A2A Outbound Allowlist

This backend requires an allowlist for all outbound A2A HTTP requests (agent card
fetching, transport negotiation, and extensions).

- Configure `A2A_PROXY_ALLOWED_HOSTS` to allow the downstream host(s).

## OpenCode Session Query (A2A Extension)

This backend supports querying OpenCode sessions and message history via an A2A
Agent Card extension declared by `opencode-a2a-serve`.

Requirements:

- Configure `A2A_PROXY_ALLOWED_HOSTS` to allow the downstream host(s).
- Create an A2A agent record pointing at the downstream Agent Card URL (e.g.
  `https://<host>/.well-known/agent-card.json`) using the `/me/a2a/agents` API.

Endpoints:

- List sessions:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions?page=1&size=20`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions:query`
- List messages for a session:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions/{session_id}/messages?page=1&size=50`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions/{session_id}/messages:query`

Optional query (passthrough):

- Provide `query` as a JSON object encoded as a string, for example:
  - `query={"tag":"foo","archived":false}`
- Or use the POST endpoints and pass `query` as a JSON object in the request body.

Notes:

- The backend discovers the JSON-RPC interface URL and method names via the Agent
  Card extension contract, and enforces the declared `page/size` pagination
  constraints (default size / max size).
- Responses include a stable envelope with `success`, `result` (upstream
  envelope), `error_code`, and `upstream_error`.

## Checks (Before Pushing)

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
