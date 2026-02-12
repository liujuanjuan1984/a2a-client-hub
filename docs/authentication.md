# Authentication Conventions

This project uses a short-lived **access token** + rotating **refresh token** model.

## Tokens

- **Access token**
  - Returned in the response body (JSON).
  - Frontend keeps it **in memory only** (do not persist to `localStorage` / `sessionStorage`).
- **Refresh token**
  - Issued and rotated by the backend as an **HttpOnly cookie**.
  - The frontend calls `POST /api/v1/auth/refresh` to restore a session after cold start / reload.

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
