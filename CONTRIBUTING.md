# Contributing to a2a-client-hub

Thanks for contributing.

## Before You Start

- Read [README.md](README.md) for repository context.
- Use English for code comments and project documentation intended for all contributors.
- Keep pull requests focused and reviewable.

## Repository Layout

- `backend/`: FastAPI + PostgreSQL + Alembic
- `frontend/`: Expo / React Native / Web
- `docs/`: cross-cutting project documentation

## Development Setup

### Backend

```bash
cd backend
uv sync --extra dev --locked
cp .env.example .env
uv run python scripts/setup_db_schema.py --create
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run start
```

Set `EXPO_PUBLIC_API_BASE_URL` in `frontend/.env` for your environment.

## Validation Requirements

Run relevant checks before opening or updating a PR.

### Backend changes

```bash
cd backend
uv sync --extra dev --locked
uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run pytest
```

### Frontend changes

```bash
cd frontend
npm install
npm run lint
export NODE_OPTIONS="--max-old-space-size=1024"
npm run check-types
npm test
```

If your change affects both backend and frontend, run both suites.

## Pull Request Guidelines

- Use a clear PR title and summary of behavior changes.
- Include validation evidence (commands + key output).
- Link related issue(s).
- Document config or behavior changes in [README.md](README.md) or [docs/](docs/) when needed.

## Security

- Never commit secrets (`.env`, private keys, tokens, credentials).
- Do not log sensitive data.

## For Automated Agents

[AGENTS.md](AGENTS.md) defines additional operational rules for coding agents. Human contributors can treat it as supplemental automation policy.
