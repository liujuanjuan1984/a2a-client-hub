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
Paste the commands you ran and key outputs.
Use scoped low-load checks by default, and use a full regression gate only when
required by `AGENTS.md`.

```bash
# backend scoped example
cd backend && uv run --locked pre-commit run --files <changed_backend_files...> --config ../.pre-commit-config.yaml
cd backend && uv run --locked pytest <changed_tests_or_module>

# frontend scoped example
cd frontend && npm run lint
cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types
cd frontend && npm test -- --findRelatedTests <changed_frontend_files...> --maxWorkers=25%

# full regression gate example (only when needed)
cd backend && uv sync --extra dev --locked
cd backend && uv run pre-commit run --all-files --config ../.pre-commit-config.yaml
cd backend && uv run pytest
cd frontend && npm install
cd frontend && npm run lint
cd frontend && export NODE_OPTIONS="--max-old-space-size=1024" && npm run check-types
cd frontend && npm test -- --maxWorkers=25%
```

## Risk and Rollback
- Risks:
- Rollback plan:

## Checklist
- [ ] Followed `AGENTS.md` and repository conventions
- [ ] No secrets committed (`.env`, keys, tokens, credentials)
- [ ] Documentation updated when needed
