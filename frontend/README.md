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

- See `docs/authentication.md`.

## Environment

- `EXPO_PUBLIC_API_BASE_URL` is required for Web and Native.
  - Recommended: `https://<your-api-host>/api/v1`
  - Web-only (same-origin reverse proxy): `/api/v1`

## Web Publish Helper

Use `npm run publish:web` to export and serve the web build locally.

- Default host: `127.0.0.1`
- Default port: `8787`
- Override with env vars: `HOST`, `PORT`
- Run in background: `DETACH=1 npm run publish:web`

## OpenCode Extension (Sessions)

If an A2A agent advertises the OpenCode session query extension (via Agent Card),
the app surfaces OpenCode session browsing under the Sessions tab:

- OpenCode sessions (paginated)

The frontend treats the upstream result as a passthrough envelope and avoids
binding to OpenCode-private schemas.

### Continue (Resume Chat)

From the sessions list, the app can "Continue" into the main Chat UI.
This uses the backend continue endpoint to obtain a stable binding
(`contextId`/`metadata`) for the selected OpenCode `session_id`, then forwards
those fields on every message so the upstream can append to the same session.

OpenCode history is rendered inline in the Chat screen (there is no standalone
"messages list" screen).
