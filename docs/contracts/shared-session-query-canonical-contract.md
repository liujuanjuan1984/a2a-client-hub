# Shared Session Query Hub-Normalized Contract

This document defines the Hub-private normalized contract consumed for shared session query handling.

It is intentionally scoped to the runtime contract that `a2a-client-hub` parses and consumes. It does not attempt to document every provider-private metadata field or method-level descriptive annotation that an upstream server may choose to publish.

## Status

- Hub-private normalization remains an internal runtime concern and is not exposed as a public contract-family field
- Supported upstream declaration families currently include:
  - `opencode`: `urn:opencode-a2a:session-query/v1`
  - `opencode` HTTPS alias: `https://github.com/Intelligent-Internet/opencode-a2a/blob/main/docs/extension-specifications.md#opencode-session-management-v1`
  - `opencode` deprecated HTTPS alias still accepted by Hub for older peers: `https://github.com/Intelligent-Internet/opencode-a2a/blob/main/docs/extension-specifications.md#opencode-session-query-v1`
  - `legacy`: `urn:shared-a2a:session-query:v1`
  - `codex`: `urn:codex-a2a:codex-session-query/v1`
- This document describes the Hub-private normalized contract only
- Hub keeps the upstream-declared URI family as a public diagnostic dimension while retaining normalization details internally

## Contract Goals

The contract exists so that Hub can:

- validate a peer during onboarding
- classify the peer as `supported`, `unsupported`, or `invalid`
- record the upstream-declared contract family while keeping Hub-private normalization internal
- choose the correct runtime parser path
- reject ambiguous or unsafe declarations early

## Required Extension Shape

The session query extension must be declared under:

```text
AgentCard.capabilities.extensions[]
```

The normalized Hub contract requires upstream declarations to provide:

- `uri`
- `params.methods.list_sessions`
- `params.methods.get_session_messages`
- `params.pagination`

For upstreams that slim down the public Agent Card and move detailed extension contracts into an authenticated extended card, Hub should prefer consuming the extended card when available. The normalized runtime contract described here still applies; only the card discovery surface changes.

The normalized contract can additionally consume upstream declarations for:

- `params.provider`
- `params.methods.prompt_async`
- `params.errors.business_codes`
- `params.result_envelope`

If `params.errors.business_codes` is declared, the published keys should match the upstream wire contract exactly. For the current OpenCode cross-repo contract, that means uppercase enum-style tokens such as `SESSION_NOT_FOUND` or `UPSTREAM_HTTP_ERROR`.

Hub normalizes those declared keys into its own lowercase internal `error_code` values during runtime parsing. The extension declaration itself should not pre-normalize them to Hub-internal naming.

## Methods

Normalized method keys consumed by Hub:

- `list_sessions`
- `get_session_messages`
- `prompt_async` (optional)

Method names must be non-empty strings.

## Pagination

Hub accepts three normalized pagination declarations:

- `page_size`
- `limit`
- `limit_and_optional_cursor`

### `page_size`

Required fields:

- `pagination.mode = "page_size"`
- `pagination.default_size`
- `pagination.max_size`

Allowed parameter names must include:

- `page`
- `size`

### `limit`

Required fields:

- `pagination.mode = "limit"`
- `pagination.default_limit`
- `pagination.max_limit`

Allowed parameter names must include:

- `limit`

Optional:

- `offset`

### `limit_and_optional_cursor`

Required fields:

- `pagination.mode = "limit_and_optional_cursor"`
- `pagination.default_limit`
- `pagination.max_limit`
- `pagination.cursor_param`
- `pagination.result_cursor_field`

Allowed parameter names must include:

- `limit`

Optional:

- `before`

Hub normalizes this declaration into its internal `limit` pagination baseline plus cursor capability metadata. This mode is therefore an additive `v1` enhancement, not a breaking protocol fork.

### Shared pagination rules

- size values must be positive integers
- `default_size` / `default_limit` must be less than or equal to the matching max value
- missing defaults or max values are invalid
- `limit_and_optional_cursor` declarations must not advertise `offset`
- unsupported pagination modes are invalid

## Result Envelope

If `params.result_envelope` is omitted, Hub falls back to the default top-level envelope:

- `items`
- `pagination`
- `raw`

If `params.result_envelope` is declared, Hub treats it as strict and only accepts these mapping keys:

- `items`
- `pagination`
- `raw`

Each declared mapping must be either:

- `true`, meaning “use the default field name”
- a non-empty string field path

Unknown keys are invalid.

## Intentional Non-Scope

The following are not part of the normalized Hub runtime envelope contract:

- method-level result documentation for non-query methods
- provider-private descriptive annotations
- ad hoc keys such as `result_envelope.by_method`

If an upstream server needs to describe method-specific result structures, that information should live in a dedicated descriptive field such as `method_contracts.<method>.result`, not inside the runtime-consumed `result_envelope` mapping.

## Hub Interpretation

At onboarding time, Hub emits:

- `status = supported | unsupported | invalid`
- `declaredContractFamily = opencode | codex | legacy` when the declaration family is recognized
- `selection_mode = direct | codex_compatibility` when Hub exposes runtime-selection metadata

At runtime, Hub uses that classification to choose:

- the direct parser path for `opencode`
- the explicit legacy compatibility path
- the explicit Codex compatibility path
- or fast-fail for unsupported / invalid contracts

## Reference Payloads

Reference payload assets live in:

- `docs/contracts/shared-session-query-reference-payloads.json`

They are intended to be copied into upstream contract tests, interoperability fixtures, or future third-party peer reviews.
