## Summary
-

## Linked Issues
- Closes #

## Change Type
- [ ] Feature (`feat`)
- [ ] Bug fix (`fix`/`bug`)
- [ ] Refactor / performance (`refactor`/`perf`)
- [ ] Tests (`tests`)
- [ ] Docs / process (`docs`/`chore`)

## Validation Evidence
Paste the commands you ran and key outputs:

```bash
# backend
cd backend && uv sync --extra dev --locked
cd backend && uv run black --check .
cd backend && uv run isort --check-only .
cd backend && uv run ruff check .
cd backend && uv run pytest

# frontend
cd frontend && npm install
cd frontend && npm run lint
cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types
cd frontend && npm test
```

## Risk and Rollback
- Risks:
- Rollback plan:

## Checklist
- [ ] Followed `AGENTS.md` and repository conventions
- [ ] No secrets committed (`.env`, keys, tokens, credentials)
- [ ] Documentation updated when needed
