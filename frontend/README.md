# a2a-client-hub (frontend)

Frontend for **a2a-client-hub**. Designed for cross-platform support (Expo / React Native / Web).

## Location

This frontend lives in `frontend/`. The backend lives in `backend/`.

## Tech Stack

- Expo
- React Native + React Native Web
- Expo Router
- NativeWind
- Zustand
- TanStack Query
- TypeScript

## Cache Strategy

Server state and client state are intentionally separated:

- Default: TanStack Query owns server state (list/detail/pagination).
- Mutations (create/update/delete) must invalidate related query keys.
- Use focus refetch only as a supplement when a screen needs stronger freshness on return.
- Zustand stores are reserved for local UI state and live interaction state (e.g. stream progress, local drafts).
- On logout/session invalidation, clear both query cache and persisted client stores to avoid cross-account residue.

## Local Persistence Resilience

- Auth token remains memory-only and is recovered via refresh-cookie flow; it is not persisted in local storage.
- Native MMKV persistence uses isolated instances by key family to reduce interference between high-volume and regular stores.
- Web persisted UI state that is chat-local or tab-local uses tab-scoped storage keys to avoid cross-tab overwrite.
- Persisted data is treated as disposable cache: invalid payloads are dropped instead of recovered.
- High-volume chat payloads use bounded persistence strategy (compaction on web quota pressure).

## Routing Conventions

This project uses Expo Router (React Navigation). The main app area uses `Tabs` (Agents/Sessions/Jobs) as the global navigation.

- Prefer `router.push()` to keep navigation history (mobile back gesture/back button, browser back).
- Use `router.replace()` only for redirects where returning to the previous screen should be prevented.
- For custom headers, a safe back strategy is:
  - `router.canGoBack() ? router.back() : router.replace("/")`

## Authentication

Authentication conventions are shared between frontend and backend:

- See [docs/authentication.md](../docs/authentication.md).

## Environment

- `EXPO_PUBLIC_API_BASE_URL` is required for Web and Native.
  - Recommended: `https://<your-api-host>/api/v1`
  - Web-only (same-origin reverse proxy): `/api/v1`

## Network Security Baseline

- iOS default is `NSAllowsArbitraryLoads=false` (`frontend/app.json`).
- Production builds should use HTTPS API endpoints.
- If local debugging requires HTTP endpoints, scope any ATS relaxations to development-only builds and do not ship them in production artifacts.

## Web Zoom and Accessibility Policy

- iOS/Android Web keeps browser zoom enabled (no `user-scalable=no`, no `maximum-scale=1`) so users can enlarge content when needed.
- The bottom tab bar is stabilized by safe-area-aware fixed heights so key navigation targets remain reachable under zoom.
- Keep input fonts at 16px on web (`frontend/global.css`) to reduce unexpected form zoom when focusing inputs.

## Time Display Strategy

- This project does not introduce a frontend i18n framework for date formatting.
- Use shared helpers in `frontend/lib/datetime.ts`:
  - `formatLocalDateTime`
  - `formatLocalDateTimeYmdHm`
- Timezone resolution:
  - Prefer `Intl.DateTimeFormat().resolvedOptions().timeZone`
  - Fallback to `UTC` when missing/invalid/unavailable
- Display format: `YYYY-MM-DD HH:mm` (24-hour)
- Fallback values:
  - Empty timestamp -> `-`
  - Invalid timestamp string -> original input (passthrough)

## Web Publish Helper

Use `npm run publish:web` to export and serve the web build locally.

- Default host: `127.0.0.1`
- Default port: `8787`
- Override with env vars: `HOST`, `PORT`
- Run in background: `DETACH=1 npm run publish:web`

## Unified Conversations

The Sessions tab now uses the backend unified conversation domain API (`POST /me/conversations:query`) and can include:

- `manual` sessions (local chat sessions persisted by backend)
- `scheduled` sessions (task execution sessions)

Notes:

- Backend `source` currently uses `manual` / `scheduled` only.
- External provider binding is represented by external binding fields (for example `external_provider` / `external_session_id`), not by a separate `source` enum value.
- Chat page SessionPicker queries backend with `agent_id` so each agent view reads its session directory from server-side authority.
- SessionPicker titles are rendered from backend `title` directly (no local history-title derivation).

Chat timeline loading is unified via `POST /me/conversations/{conversation_id}/messages:query` (`limit` + `before` cursor for backward pagination from latest window). To avoid transport contention, chat history auto-refetch is paused while a message is actively streaming. The chat composer keeps large drafts in a ref-backed buffer and applies a hard `50,000` character limit to avoid long-paste re-render spikes and unbounded memory growth.

Message id contract:

- `messages:query` returns canonical local UUIDs in `item.id`.
- Frontend store/cache keys must use `item.id` only.
- Running-session `append` and upstream `session command` now write canonical conversation messages through conversation-scoped Hub APIs instead of overlay-only cache entries.
- The chat timeline must not merge non-canonical overlay-only messages into `messages:query` results.
- Canonical history items also carry `kind` and optional `operationId` so command/action messages do not have to be rediscovered from ad hoc metadata parsing.
- `append` and `commands:run` requests should send an explicit `operationId` (UUID) for idempotent retries; message ids remain canonical message identity, not operation identity.
- Upstream A2A task state is fetched on demand via `GET /me/conversations/{conversation_id}/upstream-tasks/{task_id}`. Use `useSessionUpstreamTaskQuery` only for explicit recovery/detail views; it intentionally does not poll globally.
- Non-text block details (`reasoning`/`tool_call`) are fetched on demand via `POST /me/conversations/{conversation_id}/blocks:query`.
- Structured command results may be persisted as `data` blocks and should render as first-class canonical history blocks rather than overlay text fallbacks.
- `blocks:query` detail items include `messageId` and must match the target message before cache patching.
- `tool_call` blocks may include a normalized `toolCall` view from backend (`name`, `status`, `callId`, `arguments`, `result`, `error`); frontend should render that stable field instead of parsing provider-private raw payloads.
- Frontend stream rendering reads only the backend `hub` envelope (`hub.version`, `hub.streamBlock`, `hub.runtimeStatus`, `hub.sessionMeta`); upstream A2A `artifactUpdate` / `statusUpdate` payloads remain available for diagnostics but are no longer parsed on the client.
- Invoke payloads should carry both `userMessageId` and `agentMessageId` (UUID).
- Message status semantics are preserved from history payloads (`streaming`, `done`, `error`, `interrupted`).
- The Hub Assistant is injected into the normal agent catalog and reuses the existing permission interrupt card: read-only runs can return a `permission` interrupt, and the same UI resolves it through the dedicated hub-assistant reply endpoint.
- The Agents screen surfaces the Hub Assistant in the Shared view so it can be opened directly for hands-on testing, instead of requiring a deep link or a prior session reopen.
- Hub Assistant hub-assistant runs are conversation-backed: the frontend sends the current `conversationId`, so follow-up turns reuse the same server-side swival session instead of restarting from a stateless one-shot run.
- For Hub Assistant permission interrupts, `Allow once` resumes just the current turn, while `Always allow` enables write tools for the current Hub Assistant conversation until that server-side session expires.
- Because Hub Assistant runs now project into the normal sessions domain, the same `conversationId` can later be reopened from the Sessions directory and its persisted history survives beyond the in-memory swival runtime object.
- Reopening a Hub Assistant conversation now also recovers unresolved permission interrupts from durable session history, so the existing interrupt card can resume the pending approval flow after a refresh or reopen.

## Block-based Streaming

Chat streaming now uses a block timeline model. Each message stores an ordered `MessageBlock[]`, where each block has a `type` (`text`, `reasoning`, `tool_call`, or unknown), `content`, and `isFinished`.

Incoming chunks are reduced with this rule:

- same `block_type` => append to last block
- different `block_type` => finish previous block and push a new block

Rendering iterates blocks in order to preserve generation timeline and supports unknown block types with a fallback view.

Continue binding is unified via `POST /me/conversations/{conversation_id}:continue` so Chat always restores binding metadata through one entrypoint.

The continue payload also includes canonical binding fields:

- `conversationId`
- `workingDirectory`
- `metadata.provider`
- `metadata.externalSessionId`

Chat writes `workingDirectory` as a stable Hub field. The backend adapts it to
legacy provider-private metadata when required.

Model discovery uses the same `workingDirectory` field when the upstream agent
needs provider-specific context for provider/model listing.
