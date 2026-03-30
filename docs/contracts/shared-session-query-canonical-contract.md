# Shared Session Query Canonical Contract

This document defines the canonical Hub-consumed contract for the shared
session query extension.

It is intentionally scoped to the runtime contract that `a2a-client-hub`
parses and consumes. It does not attempt to document every provider-private
metadata field or method-level descriptive annotation that an upstream server
may choose to publish.

## Status

- Canonical extension URI: `urn:opencode-a2a:session-query/v1`
- Legacy extension URI still recognized by Hub: `urn:shared-a2a:session-query:v1`
- This document describes the canonical contract only

## Contract Goals

The contract exists so that Hub can:

- validate a peer during onboarding
- classify the peer as `canonical`, `legacy`, `unsupported`, or `invalid`
- choose the correct runtime parser path
- reject ambiguous or unsafe declarations early

## Required Extension Shape

The session query extension must be declared under:

```text
AgentCard.capabilities.extensions[]
```

The canonical declaration must provide:

- `uri`
- `params.methods.list_sessions`
- `params.methods.get_session_messages`
- `params.pagination`

The optional canonical declaration may provide:

- `params.provider`
- `params.methods.prompt_async`
- `params.errors.business_codes`
- `params.result_envelope`

If `params.errors.business_codes` is declared, the published keys should match
the upstream wire contract exactly. For the current OpenCode cross-repo
contract, that means uppercase enum-style tokens such as
`SESSION_NOT_FOUND` or `UPSTREAM_HTTP_ERROR`.

Hub normalizes those declared keys into its own lowercase internal
`error_code` values during runtime parsing. The extension declaration itself
should not pre-normalize them to Hub-internal naming.

## Methods

Canonical method keys consumed by Hub:

- `list_sessions`
- `get_session_messages`
- `prompt_async` (optional)

Method names must be non-empty strings.

## Pagination

Hub accepts three canonical pagination declarations:

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

Hub normalizes this declaration into its internal `limit` pagination baseline
plus cursor capability metadata. This mode is therefore an additive `v1`
enhancement, not a breaking protocol fork.

### Shared pagination rules

- size values must be positive integers
- `default_size` / `default_limit` must be less than or equal to the matching
  max value
- missing defaults or max values are invalid
- `limit_and_optional_cursor` declarations must not advertise `offset`
- unsupported pagination modes are invalid

## Result Envelope

If `params.result_envelope` is omitted, Hub falls back to the default top-level
envelope:

- `items`
- `pagination`
- `raw`

If `params.result_envelope` is declared, Hub treats it as strict and only
accepts these mapping keys:

- `items`
- `pagination`
- `raw`

Each declared mapping must be either:

- `true`, meaning “use the default field name”
- a non-empty string field path

Unknown keys are invalid.

## Intentional Non-Scope

The following are not part of the canonical runtime envelope contract:

- method-level result documentation for non-query methods
- provider-private descriptive annotations
- ad hoc keys such as `result_envelope.by_method`

If an upstream server needs to describe method-specific result structures, that
information should live in a dedicated descriptive field such as
`method_contracts.<method>.result`, not inside the runtime-consumed
`result_envelope` mapping.

## Hub Interpretation

At onboarding time, Hub classifies the declaration as one of:

- `canonical`
- `legacy`
- `unsupported`
- `invalid`

At runtime, Hub uses that classification to choose:

- the canonical parser path
- the explicit legacy compatibility path
- or fast-fail for unsupported / invalid contracts

## Reference Payloads

Reference payload assets live in:

- `docs/contracts/shared-session-query-reference-payloads.json`

They are intended to be copied into upstream contract tests, interoperability
fixtures, or future third-party peer reviews.
