# Backend Test Layout

Backend tests are organized by either business feature or shared concern.

## Feature Groups

- `agents/`
- `auth/`
- `external_sessions/`
- `hub_access/`
- `hub_assistant/`
- `invoke/`
- `schedules/`
- `sessions/`
- `shortcuts/`

## Shared Concern Groups

- `client/`
- `extensions/`
- `proxy/`
- `runtime/`

## Root Files

- `conftest.py`: shared pytest fixtures and configuration
- `support/`: reusable test helpers such as ASGI client wrappers and model factories

## Environment Bootstrap

- Backend tests install a controlled application environment before importing `app.core.config`.
- The bootstrap sets `BACKEND_ENV_FILE` to an empty value so tests do not load the repo-local `backend/.env`.
- Use `TEST_DATABASE_URL` or `TEST_DATABASE_NAME` to choose the PostgreSQL database for tests.
- Use `TEST_SCHEMA_NAME` to override the default schema name.
- Ambient application settings such as `DATABASE_URL`, `BACKEND_*`, `JWT_*`, and other runtime env vars are cleared during test bootstrap to keep runs reproducible.

When adding a new test:

- Put business capability coverage under the matching feature directory.
- Put reusable runtime/client/proxy assertions under the matching shared concern directory.
- Add new generic helpers under `tests/support/` instead of the tests root.
