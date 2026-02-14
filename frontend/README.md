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
- If local debugging requires HTTP endpoints, scope any ATS relaxations to
  development-only builds and do not ship them in production artifacts.

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

## Unified Sessions

The Sessions tab now uses the backend unified session domain API
(`POST /me/sessions:query`) and can include:

- `manual` sessions (local chat sessions persisted by backend)
- `scheduled` sessions (task execution sessions)
- `opencode` sessions (remote extension-backed sessions)

History loading is unified via
`POST /me/sessions/{session_id}/messages:query`.
To avoid transport contention, chat history auto-refetch is paused while a
message is actively streaming.

## Block-based Streaming

Chat streaming now uses a block timeline model.
Each assistant message stores an ordered `MessageBlock[]`, where each block
has a `type` (`text`, `reasoning`, `tool_call`, or unknown), `content`, and
`isFinished`.

Incoming chunks are reduced with this rule:

- same `block_type` => append to last block
- different `block_type` => finish previous block and push a new block

Rendering iterates blocks in order to preserve generation timeline and supports
unknown block types with a fallback view.

Continue binding is unified via
`POST /me/sessions/{session_id}:continue` so Chat always restores
`contextId`/`metadata` through one entrypoint.

The continue payload also includes canonical binding fields:

- `conversationId`
- `provider`
- `externalSessionId`
- `bindingMetadata`
