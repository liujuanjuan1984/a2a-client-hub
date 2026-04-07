# Documentation Map

This directory contains cross-cutting project documentation for `a2a-client-hub`.

Use this index to find the right document instead of repeating the same guidance across multiple READMEs.

## Reading Guide

- Repository overview and local quick start: [`README.md`](../README.md)
- Contribution workflow and validation expectations: [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- Backend module setup and backend-specific operational notes: [`backend/README.md`](../backend/README.md)
- Frontend module setup and frontend-specific behavior notes: [`frontend/README.md`](../frontend/README.md)

## Stable Reference Docs

- Architecture overview and API examples: [`architecture-and-api.md`](architecture-and-api.md)
- Compatibility notes and non-goals: [`compatibility-and-non-goals.md`](compatibility-and-non-goals.md)
- Authentication and session model: [`authentication.md`](authentication.md)
- Release automation and version synchronization: [`release-workflow.md`](release-workflow.md)
- Production security baseline: [`security-baseline.md`](security-baseline.md)

## Design Notes

- Codex discovery watch design boundary: [`codex-discovery-watch-design.md`](codex-discovery-watch-design.md)

## Contract References

- A2A error and runtime status contract: [`contracts/a2a-error-and-runtime-status-contract.md`](contracts/a2a-error-and-runtime-status-contract.md)
- Shared session query canonical contract: [`contracts/shared-session-query-canonical-contract.md`](contracts/shared-session-query-canonical-contract.md)
- Shared session query reference payloads: [`contracts/shared-session-query-reference-payloads.json`](contracts/shared-session-query-reference-payloads.json)
- Interrupt lifecycle reference cases: [`contracts/interrupt-lifecycle-message-cases.json`](contracts/interrupt-lifecycle-message-cases.json)
- Structured block serialization cases: [`contracts/structured-block-stable-serialization-cases.json`](contracts/structured-block-stable-serialization-cases.json)
- Stream block operation contract: [`contracts/stream-block-operation-contract.md`](contracts/stream-block-operation-contract.md)
- Stream block operation canonical cases: [`contracts/stream-block-operation-canonical-cases.json`](contracts/stream-block-operation-canonical-cases.json)

## Documentation Boundaries

- `README.md` should stay short and focus on repository-level orientation.
- Module READMEs should document module-local setup and behavior only.
- Stable reference docs should describe current repository behavior and maintained operating rules.
- Design notes should capture future-facing boundaries or PoC guidance and must be labeled explicitly as non-authoritative for current production behavior.
- `docs/` should own cross-cutting contracts, architecture, authentication, and production guidance.
- Contract fixtures should live under `docs/contracts/` so they can be reused by interoperability reviews and upstream peer implementations.
