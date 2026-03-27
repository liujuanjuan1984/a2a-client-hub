# OpenCode JSON-RPC Error Contract Assessment

This document records the current assessment for
[`a2a-client-hub` issue #644](https://github.com/liujuanjuan1984/a2a-client-hub/issues/644)
on the `feat/issue-644-opencode-error-contract-alignment` branch.

## Summary

The follow-up remains valid, but its current wording is broader than the code
state on `master`.

Today the Hub no longer depends on
`UPSTREAM_UNREACHABLE` / `UPSTREAM_HTTP_ERROR` /
`UPSTREAM_PAYLOAD_ERROR` as the only runtime-facing semantics. The runtime
already normalizes business-code names and upstream `data.type` values into the
Hub's lowercase canonical tokens. The remaining direct dependency is mainly in
cross-repo documentation fixtures and parser tests that still bless the legacy
uppercase names as current examples.

In short:

- The problem is still real.
- The current issue description slightly overstates the current runtime risk.
- The next change should be a contract-alignment cleanup, not a blind hard cut.

## Current Hub State

### What is already aligned

- `backend/app/integrations/a2a_error_contract.py` already canonicalizes
  upstream error `data.type` tokens such as `UPSTREAM_HTTP_ERROR` into
  lowercase Hub error codes such as `upstream_http_error`.
- `backend/app/integrations/a2a_extensions/contract_utils.py` already
  normalizes declared `errors.business_codes` keys before storing them in the
  resolver map.
- `backend/app/integrations/a2a_extensions/shared_support.py` already emits
  lowercase Hub-side extension transport errors such as `upstream_unreachable`
  and `upstream_http_error`.

This means the Hub runtime is already operating in a dual-read, canonical-write
shape for a meaningful part of the flow.

### What is still legacy-facing

The direct remaining references found on the current branch are:

- `docs/contracts/shared-session-query-reference-payloads.json`
- `backend/tests/extensions/test_session_query_extension_discovery.py`
- `backend/tests/extensions/test_opencode_provider_discovery.py`

These references matter because they act as interoperability examples and
contract fixtures for the upstream peer, even if they no longer represent the
best long-term shape of the Hub runtime.

## Upstream State

The related upstream follow-up
[`Intelligent-Internet/opencode-a2a#301`](https://github.com/Intelligent-Internet/opencode-a2a/issues/301)
is still open.

At the time of this assessment, the upstream repository still exposes the
legacy uppercase `data.type` values in
`src/opencode_a2a/jsonrpc/error_responses.py`, including:

- `UPSTREAM_HTTP_ERROR`
- `UPSTREAM_UNREACHABLE`
- `UPSTREAM_PAYLOAD_ERROR`

That means issue `#644` is not obsolete. The migration dependency still exists.

## A2A Ecosystem Fit

The current OpenCode extension family is ecosystem-compatible if it is treated
as a vendor-specific extension surface rather than a generic A2A guarantee.

The relevant A2A requirements are:

- An `AgentExtension` is identified by a unique URI and may carry
  extension-specific parameters.
- Extensions default to inactive and are activated through client/agent
  negotiation.
- Extensions must remain backward-compatible and must not break interoperability
  for clients that do not support them.
- JSON-RPC transports may include additional fields as long as they do not
  conflict with the core specification.
- A2A standardizes JSON-RPC error code usage more strongly than vendor-private
  `data.type` taxonomies.

### Practical conclusion

Using `urn:opencode-a2a:*` URIs and private `errors.business_codes` mappings is
acceptable in the A2A ecosystem.

However, these contracts should be treated as:

- vendor-private
- clearly documented
- explicitly versioned
- safe to ignore by extension-unaware clients

The main ecosystem risk is not "private protocol exists". The risk is allowing
an OpenCode-private taxonomy to drift while presenting it as if it were a
stable, generic A2A semantic.

## Assessment of Issue #644

### Is the requirement reasonable?

Yes.

The repository still publishes contract examples that normalize the upstream
legacy shape into something that looks more stable than it really is. That is a
real interoperability maintenance problem.

### Is the requirement still valid?

Yes, but the scope should be tightened.

The issue should describe the current gap more precisely:

- The Hub runtime mostly tolerates both legacy and canonical names already.
- The remaining debt is contract publication, fixture coverage, and migration
  boundary clarity.
- The migration must still be coordinated with upstream because the upstream
  server currently emits the legacy names.

### Does the current implementation direction match best practice?

Partly.

The issue is directionally correct because it calls for cross-repo coordination
and migration planning. The part that should be improved is the implied
"remove old names everywhere" framing.

Best practice for the current codebase is:

1. Keep dual-read compatibility in the Hub parser layer.
2. Move public examples and tests toward canonical lowercase names.
3. Mark legacy uppercase names as compatibility-only, not preferred examples.
4. Remove legacy compatibility only after upstream ships the new contract or
   publishes an explicit versioned migration path.

## Recommended Implementation Strategy

### Phase 1: tighten the contract statement in this repository

- Reword issue `#644` so it reflects the real current gap.
- Update contract fixtures to present canonical lowercase names as the preferred
  examples.
- Keep at least one compatibility fixture proving the parser still accepts the
  legacy uppercase names while upstream is migrating.

### Phase 2: make the migration boundary explicit

- If upstream wants to keep the same extension URI, add an explicit
  compatibility indicator such as `error_profile`, `error_contract_version`, or
  a similar field in extension params.
- If upstream wants to make an incompatible break in the declared contract,
  prefer a new extension URI version instead of silent semantic drift.

### Phase 3: remove legacy examples only after upstream convergence

- Once upstream `opencode-a2a` stops emitting the legacy names, remove the
  compatibility-first examples from Hub docs and tests.
- Keep parser compatibility for one additional transition window only if there
  is a real deployment overlap to support.

## Open Issue Bundling Recommendation

### Strongly related open issues

- `#525` is the only clearly related open issue that should be referenced in the
  same branch and PR narrative. It is the umbrella tracker for OpenCode
  extension alignment and should remain the parent context.

### Not recommended to bundle into the same implementation branch

- `#560` is broader A2A SDK migration analysis, not specifically about the
  OpenCode JSON-RPC error contract.
- `#568` is a broader A2A review and borrowing exercise, not a focused contract
  migration task.

These issues may inform the final design, but they should not be merged into
the same delivery branch unless this work expands beyond contract alignment into
repository-wide A2A capability refactoring.

## Recommended Next Actions

1. Keep issue `#644` open.
2. Narrow its wording from "Hub still depends on old types" to
   "Hub still publishes and tests legacy OpenCode error names as active contract
   examples".
3. Implement doc and fixture updates first.
4. Coordinate the actual compatibility removal with upstream
   `opencode-a2a#301`.
