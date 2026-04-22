# Engineering Hygiene Assessment for Issues 852 and 853

Date: 2026-04-22

## Scope

This assessment covers:

- Issue #852: dependency health and dependency drift.
- Issue #853: lint and type-check suppression reduction.

The assessment is based on the latest `master` branch after the upstream squash merge
of the prior task branch.

## Current Findings

### Dependency Health

The dependency-health issue is still valid.

Frontend audit still reports a low-severity test-only chain:

```text
jest-expo -> jest-environment-jsdom -> jsdom -> http-proxy-agent -> @tootallnate/once
```

`npm audit fix --force` is not an appropriate fix because it proposes a breaking
`jest-expo` change that does not match the current Expo SDK line. The current
frontend stack is on Expo SDK 54, React 19.1, and React Native 0.81, while the
latest available package line includes Expo SDK 55, Jest 30, TypeScript 6, and
Zustand 5. Those are platform or major-version migrations and should stay
separate from routine patch/minor hygiene.

Backend dependency health currently passes compatibility and vulnerability checks,
but outdated packages remain. The list includes both routine patch/minor updates
and high-risk migrations such as `a2a-sdk` 0.3.26 to 1.0.0 and Starlette 0.52 to
1.0.0.

Recommended scope for this branch:

- Keep the low-severity frontend audit finding documented unless a compatible
  upstream fix becomes available for the Expo 54/Jest 29 line.
- Avoid package-manager force fixes and broad platform upgrades.
- Treat major backend and frontend migrations as separate issues or PRs.

### Suppression Hygiene

The suppression issue is still valid.

The initial codebase scan had 290 suppression matches after excluding generated
frontend coverage output and dependency folders. The dominant categories were:

- `ARG001`: 105 matches.
- `ANN001`: 87 matches.
- `ARG002`: 46 matches.
- `SLF001`: 19 matches.
- `BLE001`: 19 matches.

Most suppressions are concentrated in backend tests, especially invoke, sessions,
extensions, and schedules tests. That matches the issue's stated pattern: fake
callbacks, flexible mock signatures, private-function tests, and intentional broad
exception handling.

Recommended scope for this branch:

- Remove only high-confidence redundant suppressions.
- Prefer typed helpers or support classes for repeated fake/mock patterns in later
  focused changes.
- Keep framework and dynamic-boundary suppressions unless the local code can be
  made clearer without changing behavior.

This branch removes seven redundant broad `# ruff: noqa: F401` suppressions from
test support modules that already declare explicit `__all__` exports. The updated
suppression inventory is 283 matches.

## Related Open Issues

No other open issue is highly related enough to require inclusion in this branch.
Searches for dependency, audit, outdated, lint, type-check, and suppression themes
only surfaced issues #852 and #853 as direct matches. Other open issues are feature,
platform, reliability, or documentation work and should remain separate.

## Verification Snapshot

Commands run during assessment:

```text
cd frontend && npm audit --audit-level=moderate
cd frontend && npm outdated
cd backend && bash scripts/dependency_health.sh
rg suppression inventory across backend and frontend sources
```
