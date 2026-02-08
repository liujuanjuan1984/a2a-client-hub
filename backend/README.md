# a2a-client-hub (backend)

FastAPI backend for **a2a-client-hub** (PostgreSQL + Alembic).

## Local Development

Install dependencies (via `uv`):

```bash
cd backend
uv sync --extra dev --locked
```

Create `backend/.env` (see `backend/.env.example`).

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

## Checks (Before Pushing)

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```
