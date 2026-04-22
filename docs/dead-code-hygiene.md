# Dead Code Hygiene

This repository maintains a lightweight dead-code hygiene workflow. The goal is to make high-confidence checks easy to run while keeping low-confidence exploratory output clearly separated from delete-on-sight cleanup.

## Stable Entry Point

Use the repository-level wrapper:

```bash
bash scripts/check-dead-code.sh
```

Available modes:

```bash
# high-confidence backend + frontend checks
bash scripts/check-dead-code.sh all

# high-confidence backend check only
bash scripts/check-dead-code.sh backend

# high-confidence frontend check only
bash scripts/check-dead-code.sh frontend

# low-confidence backend exploratory scan for manual triage only
bash scripts/check-dead-code.sh exploratory-backend
```

## What Each Mode Means

### High-confidence checks

High-confidence checks are the maintained hygiene path and are appropriate for local cleanup work:

- Backend: `backend/scripts/run_vulture.sh`
- Frontend: `frontend/scripts/check-unused-exports.sh`

These checks are still advisory, but their signal is intentionally strong enough to support normal engineering cleanup.

The frontend check uses `frontend/tsconfig.diagnostics.json` so diagnostics stay scoped to source and test-support files instead of generated output such as coverage reports, Expo caches, builds, or installed dependencies. Repository-level ripgrep diagnostics also use `.ignore` to skip generated directories and lockfiles by default; use `rg -u` when those files are the explicit target.

### Exploratory backend scan

`bash scripts/check-dead-code.sh exploratory-backend` runs a lower-confidence `vulture` pass. Use it only to generate a triage list that a human reviews carefully.

Do not treat exploratory output as direct delete guidance.

Common false positives include:

- FastAPI route handlers and websocket endpoints
- Pydantic validators and model hooks
- SQLAlchemy hooks
- pytest fixtures and test-only doubles
- dynamically referenced integration entry points

## Recommended Usage

Use dead-code checks when one of these applies:

- A refactor removes or reshapes helpers, services, or adapters
- A cleanup PR touches exports, route helpers, or integration glue
- You want a quick hygiene pass before finishing a focused maintenance branch

Avoid making these checks part of every default low-load verification run. They are intended as lightweight hygiene tools, not mandatory per-change gates.

## Review Guidance

When reporting dead-code cleanup in a PR:

- State whether you ran the high-confidence path, the exploratory path, or both
- Call out any exploratory findings that were intentionally left untouched
- Prefer follow-up issues over opportunistic broad deletion when confidence is low
