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

Default local verification mode is the same low-load, serial, scope-based flow defined in [AGENTS.md](AGENTS.md). CI may still run broader checks.

### Backend changes

```bash
cd backend
uv run --locked pre-commit run --files <changed_backend_files...> --config ../.pre-commit-config.yaml
uv run --locked pytest <changed_tests_or_module>
```

Notes:

- Keep `backend/pyproject.toml` and `backend/uv.lock` synchronized. Metadata-only version bumps must update the lockfile in the same change.
- If `cd backend && uv lock --check` fails, treat it as lockfile drift and fix it explicitly instead of relying on `uv run` to rewrite `uv.lock` during routine verification.
- Run `uv sync --extra dev --locked` only when dependencies changed or the local environment drifted.
- Use full backend regressions when a human asks for them, when a PR is moving out of Draft, or when scoped checks are insufficient for cross-module changes.

### Frontend changes

```bash
cd frontend
npm run lint
export NODE_OPTIONS="--max-old-space-size=1024"
npm run check-types
npm test -- --findRelatedTests <changed_frontend_files...> --maxWorkers=25%
```

Notes:

- Run `npm install` only when dependencies changed or the local environment drifted.
- If your change affects both backend and frontend, run backend checks first, then frontend checks.
- Use full frontend regressions when a human asks for them, when a PR is moving out of Draft, or when scoped checks are insufficient for cross-module changes.

## Pull Request Guidelines

- Use a clear PR title and summary of behavior changes.
- Include validation evidence (commands + key output).
- Link related issue(s).
- Document config or behavior changes in [README.md](README.md) or [docs/](docs/) when needed.

## Dependency Automation

- Dependabot keeps backend updates grouped weekly for `backend/` (`uv`).
- Frontend npm updates are split into smaller patch/minor review lanes for Expo SDK, React Native core, state/storage, development tooling, and miscellaneous runtime packages.
- Semver-major frontend updates are intentionally ignored for automatic PR creation and are expected to be planned manually.
- React / React Native core and renderer-aligned minor upgrades are planned manually because they require coordinated Expo SDK, test preset, and peer dependency review.
- Existing audit workflows remain in place for explicit vulnerability review and do not replace human triage.

## Security

- Never commit secrets (`.env`, private keys, tokens, credentials).
- Do not log sensitive data.

## For Automated Agents

[AGENTS.md](AGENTS.md) defines additional operational rules for coding agents. Human contributors can treat it as supplemental automation policy.
