# Production Security Baseline

This project supports local developer convenience defaults, but production
deployments must use hardened settings.

Set `APP_ENV=production` in `backend/.env` to enable strict startup validation.
The backend will refuse to start when baseline checks fail.

## Backend Baseline (Enforced)

When `APP_ENV=production`, the backend enforces:

- `JWT_ALGORITHM` is restricted to asymmetric algorithms (`RS*`/`ES*`) with
  explicit `JWT_PRIVATE_KEY_PEM` and `JWT_PUBLIC_KEY_PEM`.
- `WS_TICKET_SECRET_KEY` is not a weak/default placeholder.
- `AUTH_REFRESH_COOKIE_SECURE=true`.
- `A2A_PROXY_ALLOWED_HOSTS` is non-empty and does not contain literal `*`.
- `BACKEND_CORS_ORIGINS` does not contain `*` or localhost origins.
- `WS_REQUIRE_ORIGIN=true`.
- `WS_ALLOWED_ORIGINS` is explicitly configured and does not contain `*` or
  localhost origins.

## Cookie / TLS Guidance

- Use HTTPS in production.
- Keep refresh token in HttpOnly cookie.
- Use `AUTH_REFRESH_COOKIE_SECURE=true`.
- Keep `AUTH_REFRESH_COOKIE_SAMESITE=lax` unless cross-site behavior is required.
- If `AUTH_REFRESH_COOKIE_SAMESITE=none`, `AUTH_REFRESH_COOKIE_SECURE` must stay
  `true`.

## CORS / Origin Guidance

- Configure explicit frontend origins in `BACKEND_CORS_ORIGINS`.
- Configure explicit WebSocket origins in `WS_ALLOWED_ORIGINS`.
- Do not use wildcard origins in production.
- Do not include localhost/loopback origins in production.

## Outbound Network Guidance

- Restrict `A2A_PROXY_ALLOWED_HOSTS` to approved downstream hosts/domains.
- Avoid over-broad host rules.
- Review allowlist entries during release reviews.

## Dependency Audit Policy

- Blocking CI checks audit backend runtime dependencies exported from `uv.lock`.
- Development-only dependency findings should be triaged through normal issue
  tracking and maintenance work without blocking unrelated product changes.
- Treat runtime dependency findings as release-blocking until fixed or
  explicitly triaged.
- Treat development dependency findings as maintenance work unless they affect
  production execution paths.

## Client Network Policy

- iOS default is `NSAllowsArbitraryLoads=false` in `frontend/app.json`.
- Do not ship production builds that globally allow arbitrary HTTP loads.
- If HTTP exceptions are needed for local debugging, use development-only build
  configuration and never reuse it in production artifacts.
