# Backend Test Layout

Backend tests are organized by either feature or shared concern.

## Feature Groups

- `api/`
- `auth/`
- `shortcuts/`
- `personal_agents/`
- `shared_a2a_agents/`
- `invoke/`
- `schedules/`
- `sessions/`
- `extensions/`

## Shared Concern Groups

- `client/`
- `proxy/`
- `runtime/`
- `shared/`

## Root Files

- `conftest.py`: shared pytest fixtures and configuration
- `support/`: reusable test helpers such as ASGI client wrappers and model factories

When adding a new test:

- Put business capability coverage under the matching feature directory.
- Put reusable runtime/client/proxy assertions under the matching shared concern directory.
- Add new generic helpers under `tests/support/` instead of the tests root.
