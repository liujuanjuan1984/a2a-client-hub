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
- See [`docs/security-baseline.md`](../docs/security-baseline.md) for required cookie/CORS/origin/TLS settings.

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

## Backend Structure

The backend now uses a practical feature-based structure for business-facing entrypoints and orchestration code.

Current direction:

- Cross-cutting layers remain under `app/api`, `app/core`, `app/db`, `app/integrations`, and `app/platform`.
- Feature-owned code lives under `app/features/<feature_name>/`.
- Migrated feature routes, schemas, and facades should be imported from `app/features/...` directly.

Feature-owned areas already organized under `app/features/`:

- `app/features/auth/`
- `app/features/extension_capabilities/`
- `app/features/hub_agents/`
- `app/features/invitations/`
- `app/features/invoke/`
- `app/features/opencode_sessions/`
- `app/features/personal_agents/`
- `app/features/schedules/`
- `app/features/sessions/`
- `app/features/shortcuts/`

This keeps the runtime entrypoints aligned with business capabilities and makes the import graph easier to reason about over time.

## Test Layout

Backend tests are being grouped under `backend/tests/<group_name>/` so related coverage stays close together.

Current layout direction:

- Feature directories such as `tests/invoke/`, `tests/sessions/`, and `tests/hub_agents/`
- Shared capability directories such as `tests/client/`, `tests/runtime/`, `tests/proxy/`, and `tests/shared/`
- Shared fixtures remain at the `backend/tests/` root, and reusable helpers live under `backend/tests/support/`

## Incremental mypy Gate

The backend uses a phased mypy gate for changed files instead of a full-repo type gate.

Current scope:

- `backend/app/**/*.py`

Useful commands:

```bash
cd backend
uv run bash scripts/mypy_changed.sh
uv run bash scripts/mypy_changed.sh app/features/auth/schemas.py
```

## Lockfile Hygiene

`backend/pyproject.toml` and `backend/uv.lock` must remain synchronized.

- Run `cd backend && uv lock --check` after dependency or version metadata changes.
- If the check fails, update `backend/uv.lock` in an explicit lockfile change instead of letting `uv run` rewrite the file during normal lint/test execution.
- For routine verification, prefer `uv run --locked ...` so local checks fail fast on lock drift without mutating the worktree.

## AsyncSession Lifecycle

The backend treats `AsyncSession` as a short-lived unit-of-work boundary, not as a long-running workflow container.

Engineering rules:

- Do not keep an active `AsyncSession` open across external network I/O, streaming, polling, retries, scheduler waits, or other long-running background steps.
- Split complex flows into explicit phases such as `load/lock -> commit -> external I/O -> reopen -> finalize`.
- Request-scoped dependencies may provide a session for validation and local DB work, but route handlers should close any read-only transaction before entering long-lived invoke or streaming flows.
- Background jobs should prefer bounded per-batch sessions instead of reusing one session across an entire drain loop when repeated batches are possible.

Recent examples:

- `app/features/schedules/job.py` keeps scheduler claim/finalize work in short sessions and releases DB state before remote invoke.
- `app/features/invoke/route_runner.py` keeps session recovery in short transactions instead of tying invoke lifetime to request-scoped DB state.

## A2A Outbound Allowlist

This backend requires an allowlist for all outbound A2A HTTP requests (agent card fetching, transport negotiation, and extensions).

- Configure `A2A_PROXY_ALLOWED_HOSTS` to allow the downstream host(s).
- In production (`APP_ENV=production`), this list must be non-empty and must not contain literal `*`.

## Hub A2A Catalog (Admin-Managed)

This backend supports an admin-managed global A2A catalog ("hub agents") with:

- `public`: visible/invokable by all users.
- `allowlist`: visible/invokable only by allowlisted users (others get `404`).
- System-managed credentials: admin can store an encrypted bearer token which is never returned to normal users.

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

## Shared Session Query / Interrupt Callback Compatibility

This backend supports querying upstream sessions and message history via a shared A2A Agent Card extension contract.

The current examples in this section use OpenCode-flavored contracts because that profile is deeply exercised in this repository, but the Hub is not meant to be OpenCode-only. Other coding-agent peers, including Codex-family A2A deployments, can participate when they publish a compatible A2A surface.

Contract references:

- Canonical contract: [`docs/contracts/shared-session-query-canonical-contract.md`](../docs/contracts/shared-session-query-canonical-contract.md)
- Reference payloads: [`docs/contracts/shared-session-query-reference-payloads.json`](../docs/contracts/shared-session-query-reference-payloads.json)
- Hub also accepts the Codex compatibility URI `urn:codex-a2a:codex-session-query/v1` when its declared pagination and control semantics stay losslessly mappable to the Hub-private normalized `a2a_client_hub` session-query contract family.
- Cross-cutting API examples: [`docs/architecture-and-api.md`](../docs/architecture-and-api.md)
- Compatibility notes and non-goals: [`docs/compatibility-and-non-goals.md`](../docs/compatibility-and-non-goals.md)

Requirements:

- Configure `A2A_PROXY_ALLOWED_HOSTS` to allow the downstream host(s).
- Create an A2A agent record pointing at the downstream Agent Card URL (e.g. `https://<host>/.well-known/agent-card.json`) using the `/me/a2a/agents` API.

The examples below still use OpenCode-flavored naming where the upstream profile itself is provider-specific.

Endpoints:

- Read generic extension capabilities:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/capabilities`
  - The response also includes a `compatibilityProfile` block when the upstream declares the compatibility-profile extension (either the standard `urn:a2a:compatibility-profile/v1` URI or the newer `opencode-a2a` HTTPS specification URI), exposing `extensionRetention`, `methodRetention`, `serviceBehaviors`, and `consumerGuidance` for Hub-side diagnostics.
- Discover generic model providers:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/models/providers:list`
    - body: `{ "session_metadata": { "shared": { "model": { "providerID": "openai", "modelID": "gpt-5" } } } }`
- Discover generic models:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/models:list`
    - body: `{ "provider_id": "openai", "session_metadata": { "shared": { "model": { "providerID": "openai", "modelID": "gpt-5" } } } }`
- List sessions:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions?page=1&size=20`
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions?page=1&size=20&directory=services/api&roots=true&start=40&search=planner`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions:query`
    - body example: `{"page":1,"size":20,"filters":{"directory":"services/api","roots":true,"start":40,"search":"planner"},"query":{"status":"open"}}`
    - the Hub contract keeps `filters.directory`, `filters.roots`, `filters.start`, and `filters.search` stable, then maps them to the upstream session-query contract declared by the runtime

Validation:

- `POST /api/v1/me/a2a/agents/{agent_id}/card:validate` now returns a `compatibility_profile` diagnostic when the upstream card declares the compatibility-profile extension.
- When an upstream advertises top-level `supportsAuthenticatedExtendedCard`, Hub prefers fetching the authenticated extended card so provider-private extension contracts can still be resolved even if the public Agent Card is intentionally slimmed down.
- Continue a session:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}:continue`
- Trigger async prompt for an existing upstream session:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}:prompt-async`
    - body: `{"request":{"parts":[{"type":"text","text":"Continue and summarize next steps."}],"noReply":true},"metadata":{"provider":"opencode","externalSessionId":"ses-123"}}`
- List messages for a session:
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}/messages?page=1&size=50`
  - `GET /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}/messages?page=1&size=50&before=<opaque-cursor>`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/sessions/{session_id}/messages:query`
    - body example: `{"page":1,"size":50,"before":"<opaque-cursor>","include_raw":false}`
    - cursor-capable runtimes also return: `{"result":{"items":[...],"pagination":{"page":1,"size":50},"pageInfo":{"hasMoreBefore":true,"nextBefore":"<opaque-cursor>"}}}`
- Reply interrupt callbacks:
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts:recover`
    - body: `{ "sessionId": "ses-123" }`
    - returns: `{ "items": [{ "requestId": "...", "sessionId": "ses-123", "type": "permission|question", "details": { ... }, "expiresAt": 123.0, "source": "recovery" }] }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/permission:reply`
    - body: `{ "request_id": "...", "reply": "once|always|reject" }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/question:reply`
    - body: `{ "request_id": "...", "answers": [["A"], ["B"]] }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/question:reject`
    - body: `{ "request_id": "..." }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/permissions:reply`
    - body: `{ "request_id": "...", "permissions": { "fileSystem": { "write": ["/workspace/project"] } }, "scope": "turn|session" }`
  - `POST /api/v1/me/a2a/agents/{agent_id}/extensions/interrupts/elicitation:reply`
    - body: `{ "request_id": "...", "action": "accept|decline|cancel", "content": { "approved": true } }`
  - Optional metadata for all interrupt callbacks:
    - `{ "metadata": { "provider": "opencode", "requestScope": "shared" } }`

Optional query (passthrough):

- Provide `query` as a JSON object encoded as a string, for example:
  - `query={"tag":"foo","archived":false}`
- Or use the POST endpoints and pass `query` as a JSON object in the request body.

Notes:

- `before` is a Hub-stable request field for extension session message history. The backend maps it to the upstream runtime's declared cursor param when the session-query contract advertises cursor pagination support.
- `result.pageInfo.nextBefore` is the Hub-stable cursor field. It is derived from the upstream runtime's declared cursor result field and omitted when the runtime does not expose cursor pagination.
- The backend discovers the JSON-RPC interface URL and method names via the Agent Card extension contract, and enforces the declared pagination constraints (`page/size`, `limit`, or `limit + cursor`, including default/max bounds).
- When the upstream card declares the wire-contract extension, the backend also preflights custom JSON-RPC calls against `all_jsonrpc_methods` and `extensions.conditionally_available_methods`, returning a normalized `method_not_supported` or `method_disabled` result before making an upstream call.
- Responses include a stable envelope with `success`, `result` (upstream envelope), `error_code`, and `upstream_error`.
- Non-2xx HTTP errors are normalized under `detail`, for example: `{"detail":{"message":"...","error_code":"...","source":"...","jsonrpc_code":...}}`.
- Interrupt callback payloads intentionally follow the strict upstream contract: `request_id` is required; legacy fields such as `requestID`, `decision`, `allow` or `deny` are not accepted.
- `permissions:reply` and `elicitation:reply` are Hub-stable routes for the new shared interrupt callback methods. The backend keeps upstream method names and provider-specific JSON-RPC details behind the extension compatibility layer.
- Interrupt recovery is exposed as a Hub-stable route. The backend hides the upstream provider-private JSON-RPC methods and merges the recovery views for pending permissions/questions before returning them to the frontend.

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

The backend now exposes a unified conversation read model for manual, scheduled, and OpenCode sessions:

- `POST /api/v1/me/conversations:query`
- `POST /api/v1/me/conversations/{conversation_id}/messages:query`
- `POST /api/v1/me/conversations/{conversation_id}/blocks:query`
- `POST /api/v1/me/conversations/{conversation_id}:continue`

`conversations:query` supports optional `agent_id` filtering so Chat session directory views can be fetched per-agent directly from backend.

`continue` now returns the canonical fields and binding metadata:

- `conversationId` (canonical conversation id)
- `source` (canonical source)
- `metadata`:
  - `provider` (external provider key)
  - `externalSessionId` (external session identifier)
  - `contextId` (A2A context id)
  - `<metadata_key>` (strict upstream session-binding key from `urn:opencode-a2a:opencode-session-binding/v1`, e.g. `opencode_session_id`)

Client-generated chat sessions should use raw UUID conversation IDs, for example `550e8400-e29b-41d4-a716-446655440000`.

Message query contract boundary:

- `messages:query` is the primary chat read model and returns ordered message timeline items with block payloads plus backward cursor pagination (`pageInfo.hasMoreBefore`, `pageInfo.nextBefore`).
- `SessionMessageItem.id` is the canonical local message UUID for all roles.
- Message body is persisted and queried via ordered blocks for all roles (`user`/`agent`/`system`).
- `messages:query` keeps full `content` for `text` blocks; `reasoning`/`tool_call` block `content` is fetched via `blocks:query` on demand.
- `tool_call` blocks also expose a normalized `toolCall` view (`name`, `status`, `callId`, `arguments`, `result`, `error`) so frontend rendering does not need to parse provider-private payload shapes directly.
- `blocks:query` returns per-block `messageId` so clients can validate cache injection ownership before patching local message state.
- For streaming `artifact-update`, upstream `message_id/event_id` are treated as optional hints; hub rewrites outgoing stream payloads with stable local `message_id/event_id/seq` for frontend consumption.

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
