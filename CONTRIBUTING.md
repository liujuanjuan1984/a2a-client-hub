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

To avoid keeping multiple setup guides in sync, use:

- [README.md](README.md) for repository-level quick start
- [backend/README.md](backend/README.md) for backend local setup and runtime notes
- [frontend/README.md](frontend/README.md) for frontend environment and behavior notes

## Validation Requirements

Run relevant checks before opening or updating a PR.

### Backend changes

```bash
cd backend
uv sync --extra dev --locked
uv run --locked pre-commit run --all-files --config ../.pre-commit-config.yaml
uv run --locked pytest
```

Notes:

- Keep `backend/pyproject.toml` and `backend/uv.lock` synchronized. Metadata-only version bumps must update the lockfile in the same change.
- If `cd backend && uv lock --check` fails, treat it as lockfile drift and fix it explicitly instead of relying on `uv run` to rewrite `uv.lock` during routine verification.

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
