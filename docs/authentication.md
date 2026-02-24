# Authentication Conventions

This project uses a short-lived **access token** + rotating **refresh token** model.

## Tokens

- **Access token**
  - Returned in the response body (JSON).
  - Frontend keeps it **in memory only** (do not persist to `localStorage` / `sessionStorage`).
- **Refresh token**
  - Issued and rotated by the backend as an **HttpOnly cookie**.
  - The frontend calls `POST /api/v1/auth/refresh` to restore a session after cold start / reload.

## Frontend Refresh Strategy

The frontend follows a hybrid strategy:

- **Proactive refresh (primary path)**
  - Requests check whether the access token is near expiry before sending.
  - Lead time is TTL-aware (dynamic), not a fixed constant.
  - Additional refresh checks run when the app returns to foreground, when the page becomes visible, and when network connectivity is restored.

- **Reactive refresh (fallback path)**
  - Protected requests retry once after `401` by forcing a refresh.
  - If retry still fails, the client transitions to an expired-auth state.
  - `403` is treated as an authorization denial and does not trigger refresh.

## Failure Handling

- Refresh requests use a short timeout to avoid long UI stalls.
- Concurrent refresh attempts are single-flight to prevent storms.
- Auth-expired cleanup is centralized and guarded to avoid repeated reset loops.
- Auth failures short-circuit transport fallback chains (WebSocket/SSE/JSON) instead of repeatedly cascading.

## Session State Model

Frontend session state tracks:

- Access token value (memory only)
- Token expiry metadata (`expires_in` projected to an absolute timestamp)
- Auth status (`authenticated`, `refreshing`, `expired`)
- Auth version counter for stale-request protection

## Web Cookie Requirements

- In production, HTTPS is required when refresh cookies are marked `Secure`.
- Web requests must send cookies:
  - `fetch(..., { credentials: "include" })`

## Production Baseline

For production deployments:

- Set `APP_ENV=production` in backend settings.
- Keep `AUTH_REFRESH_COOKIE_SECURE=true`.
- Keep explicit allowlists for `BACKEND_CORS_ORIGINS` and `WS_ALLOWED_ORIGINS`.
- Keep `WS_REQUIRE_ORIGIN=true`.

See [security baseline](security-baseline.md) for the full hardening checklist.

## API Base URL

Frontend uses `EXPO_PUBLIC_API_BASE_URL`:

- Recommended (works on Web and Native): `https://<your-api-host>/api/v1`
- Web-only (same-origin reverse proxy): `/api/v1`
  - Native must use an absolute URL.
