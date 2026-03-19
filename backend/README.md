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

## Incremental mypy Gate

The backend uses a phased mypy gate for changed files instead of a full-repo
type gate.

Current scope:

- `backend/app/**/*.py`

Useful commands:

```bash
cd backend
uv run bash scripts/mypy_changed.sh
uv run bash scripts/mypy_changed.sh app/schemas/auth.py
```

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

This backend supports querying upstream sessions and message history via a
shared A2A Agent Card extension contract.

Contract references:

- Canonical contract:
  [`docs/contracts/shared-session-query-canonical-contract.md`](../docs/contracts/shared-session-query-canonical-contract.md)
- Reference payloads:
  [`docs/contracts/shared-session-query-reference-payloads.json`](../docs/contracts/shared-session-query-reference-payloads.json)
- Cross-cutting API examples:
  [`docs/architecture-and-api.md`](../docs/architecture-and-api.md)

Requirements:

- Configure `A2A_PROXY_ALLOWED_HOSTS` to allow the downstream host(s).
- Create an A2A agent record pointing at the downstream Agent Card URL (e.g.
  `https://<host>/.well-known/agent-card.json`) using the `/me/a2a/agents` API.

Endpoints:

- Read generic extension capabilities:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/capabilities`
- Discover generic model providers:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/models/providers:list`
    - body:
      `{ "session_metadata": { "shared": { "model": { "providerID": "openai", "modelID": "gpt-5" } } } }`
- Discover generic models:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/models:list`
    - body:
      `{ "provider_id": "openai", "session_metadata": { "shared": { "model": { "providerID": "openai", "modelID": "gpt-5" } } } }`
- List sessions:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions?page=1&size=20`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions:query`
- Continue a session:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}:continue`
- Trigger async prompt for an existing upstream session:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}:prompt-async`
    - body:
      `{"request":{"parts":[{"type":"text","text":"Continue and summarize next steps."}],"noReply":true},"metadata":{"provider":"opencode","externalSessionId":"ses-123"}}`
- List messages for a session:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}/messages?page=1&size=50`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}/messages:query`
- Reply interrupt callbacks:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/permission:reply`
    - body: `{ "request_id": "...", "reply": "once|always|reject" }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/question:reply`
    - body: `{ "request_id": "...", "answers": [["A"], ["B"]] }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/question:reject`
    - body: `{ "request_id": "..." }`
  - Optional metadata for all interrupt callbacks:
    - `{ "metadata": { "provider": "opencode", "requestScope": "shared" } }`

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

Unified error semantics (`error_code` -> HTTP status):

| Scenario | error_code | HTTP Status |
|---|---|---|
| Session not found | `session_not_found` | 404 |
| Session access forbidden | `session_forbidden` | 403 |
| Outbound domain not allowed / invalid configuration | `outbound_not_allowed` | 403 |
| Runtime/session input invalid | `runtime_invalid` | 400 |
| Invalid request payload | `invalid_request` | 400 |
| Invalid params / invalid field | `invalid_params` | 400 |
| Invalid query payload | `invalid_query` | 400 |
| Upstream method disabled by contract | `method_disabled` | 403 |
| Upstream method not supported | `method_not_supported` | 400 |
| Interrupt request not found | `interrupt_request_not_found` | 404 |
| Interrupt request expired | `interrupt_request_expired` | 409 |
| Interrupt type mismatch | `interrupt_type_mismatch` | 409 |
| Upstream unreachable | `upstream_unreachable` | 503 |
| Upstream HTTP non-2xx | `upstream_http_error` | 502 |
| Upstream payload contract error | `upstream_payload_error` | 502 |
| Upstream JSON-RPC business error (unclassified) | `upstream_error` | 502 |
| Agent unavailable | `agent_unavailable` | 503 |
| Request timeout | `timeout` | 504 |
| Client reset required | `client_reset` | 502 |
| Contract unsupported / incompatible during execution | `not_supported` | 400 |
| Extension contract validation failed | `extension_contract_error` | 400 |
| Duplicate concurrent call in the same session | `invoke_inflight` | 409 |

Default mapping:

- Unrecognized `error_code` returns `502` (A2A invoke / extension treated as upstream failure).
- Other `4xx/5xx` values follow the table above.

## Unified Conversation Domain API

The backend now exposes a unified conversation read model for manual,
scheduled, and OpenCode sessions:

- `POST /api/v1/me/conversations:query`
- `POST /api/v1/me/conversations/{conversation_id}/messages:query`
- `POST /api/v1/me/conversations/{conversation_id}/blocks:query`
- `POST /api/v1/me/conversations/{conversation_id}:continue`

`conversations:query` supports optional `agent_id` filtering so Chat session
directory views can be fetched per-agent directly from backend.

`continue` now returns the canonical fields and binding metadata:

- `conversationId` (canonical conversation id)
- `source` (canonical source)
- `metadata`:
  - `provider` (external provider key)
  - `externalSessionId` (external session identifier)
  - `contextId` (A2A context id)
  - `<metadata_key>` (strict upstream session-binding key from
    `urn:opencode-a2a:opencode-session-binding/v1`, e.g. `opencode_session_id`)

Client-generated chat sessions should use raw UUID conversation IDs, for example
`550e8400-e29b-41d4-a716-446655440000`.

Message query contract boundary:

- `messages:query` is the primary chat read model and returns ordered
  message timeline items with block payloads plus backward cursor pagination
  (`pageInfo.hasMoreBefore`, `pageInfo.nextBefore`).
- `SessionMessageItem.id` is the canonical local message UUID for all roles.
- Message body is persisted and queried via ordered blocks for all roles
  (`user`/`agent`/`system`).
- `messages:query` keeps full `content` for `text` blocks; `reasoning`/`tool_call`
  block `content` is fetched via `blocks:query` on demand.
- `blocks:query` returns per-block `messageId` so clients can validate cache
  injection ownership before patching local message state.
- For streaming `artifact-update`, upstream `message_id/event_id` are treated as
  optional hints; hub rewrites outgoing stream payloads with stable local
  `message_id/event_id/seq` for frontend consumption.

Invoke message id contract:

- Clients may provide `userMessageId` and `agentMessageId` in invoke payloads.
- When provided, both values must be UUIDs and are treated as canonical local message ids.
- Message id conflicts are returned as `message_id_conflict` (HTTP 409).

## Checks (Before Pushing)

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
