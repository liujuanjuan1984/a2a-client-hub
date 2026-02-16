# a2a-client-hub (backend)

FastAPI backend for **a2a-client-hub** (PostgreSQL + Alembic).

## Local Development

Install dependencies (via `uv`):

```bash
cd backend
uv sync --extra dev --locked
```

Create `backend/.env` (see `backend/.env.example`).

Production note:

- Set `APP_ENV=production` to enable strict security baseline checks at startup.
- See [`docs/security-baseline.md`](../docs/security-baseline.md) for required
  cookie/CORS/origin/TLS settings.

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
- In production (`APP_ENV=production`), this list must be non-empty and must
  not contain literal `*`.

## Hub A2A Catalog (Admin-Managed)

This backend supports an admin-managed global A2A catalog ("hub agents") with:

- `public`: visible/invokable by all users.
- `allowlist`: visible/invokable only by allowlisted users (others get `404`).
- System-managed credentials: admin can store an encrypted bearer token which is never
  returned to normal users.

Endpoints:

- Admin CRUD:
  - `GET/POST/PUT/DELETE /api/v1/admin/a2a/agents`
  - `GET /api/v1/admin/a2a/agents/{agent_id}`
  - `GET/POST/DELETE /api/v1/admin/a2a/agents/{agent_id}/allowlist`
- User catalog:
  - `GET /api/v1/a2a/agents`
  - `POST /api/v1/a2a/agents/{agent_id}/invoke`

Credentials:

- Configure `HUB_A2A_TOKEN_ENCRYPTION_KEY` (falls back to `USER_LLM_TOKEN_ENCRYPTION_KEY`).

## OpenCode Session Query & Interrupt Callback (A2A Extension)

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
- Continue a session:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions/{session_id}:continue`
- List messages for a session:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions/{session_id}/messages?page=1&size=50`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/sessions/{session_id}/messages:query`
- Reply interrupt callbacks:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/interrupts/permission:reply`
    - body: `{ "request_id": "...", "reply": "once|always|reject" }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/interrupts/question:reply`
    - body: `{ "request_id": "...", "answers": [["A"], ["B"]] }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/opencode/interrupts/question:reject`
    - body: `{ "request_id": "..." }`

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
- Interrupt callback payloads intentionally follow the strict upstream contract:
  `request_id` is required; legacy fields such as `requestID`, `decision`,
  `allow` or `deny` are not accepted.

## Unified Conversation Domain API

The backend now exposes a unified conversation read model for manual,
scheduled, and OpenCode sessions:

- `POST /api/v1/me/conversations:query`
- `POST /api/v1/me/conversations/{conversation_id}/messages:query`
- `POST /api/v1/me/conversations/{conversation_id}:continue`

`continue` now returns canonical binding fields plus invoke metadata:

- `conversationId` (canonical conversation id)
- `provider` (external provider key)
- `externalSessionId` (external session identifier)
- `contextId` (A2A context id)
- `metadata.<metadata_key>` (strict upstream session-binding key from
  `urn:opencode-a2a:opencode-session-binding/v1`)

Client-generated chat sessions should use raw UUID conversation IDs, for example
`550e8400-e29b-41d4-a716-446655440000`.

## Checks (Before Pushing)

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
