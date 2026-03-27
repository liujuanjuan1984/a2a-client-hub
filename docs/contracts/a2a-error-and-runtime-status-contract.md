# A2A Error And Runtime Status Contract

This repository treats upstream A2A protocol data as two separate layers:

- `error_code`: Hub canonical business semantic used by UI, HTTP status mapping, and stable client logic
- `jsonrpc_code`: raw upstream JSON-RPC numeric code preserved for diagnostics and advanced recovery

When upstream peers publish string tokens such as `error.data.type` or
extension `errors.business_codes` keys, the Hub treats those values as
wire-contract tokens and preserves their external contract meaning separately
from the Hub's own canonical `error_code`.

## External vs Internal Naming

- External upstream or extension contract tokens should follow the publisher's
  declared wire format. For the current OpenCode contract, that means
  uppercase enum-style tokens such as `UPSTREAM_HTTP_ERROR`.
- Internal Hub `error_code` values are canonicalized to lowercase
  `snake_case`, such as `upstream_http_error`.
- The mapping layer is intentionally lossy on casing so the Hub can preserve a
  stable internal semantic even when upstream token formatting differs.
- `upstream_error.data.type` and declared extension `business_codes` should be
  treated as external compatibility inputs, not as the Hub's canonical storage
  format.

## Error Envelope

The hub-facing invoke and extension APIs use the same structured error fields:

- `error_code`
- `source`
- `jsonrpc_code`
- `missing_params`
- `upstream_error`

### Mapping priority

When an upstream JSON-RPC error is available, the hub resolves `error_code` in this order:

1. `error.data.type`
2. declared `business_codes`
3. standard JSON-RPC codes
4. existing declared error token
5. normalized message fallback

The raw numeric code is preserved separately as `jsonrpc_code`.

### OpenCode-specific guidance

For the current OpenCode JSON-RPC extension contract:

- `error.data.type` values are expected to arrive as uppercase wire tokens.
- `errors.business_codes` examples should remain uppercase to match the
  published cross-repo contract.
- The Hub still normalizes those values into lowercase internal `error_code`
  strings before applying UI logic, HTTP status mapping, and persistence.

## Runtime Status Contract

The hub advertises a `runtimeStatus` capability object with contract version `v1`.
Frontend runtime parsing uses this capability contract when available and falls
back to the built-in `v1` default only when capability data is unavailable.

### Canonical states

- `working`
- `input-required`
- `auth-required`
- `completed`
- `failed`
- `cancelled`

### Terminal stream states

These states are expected to end the current stream transport session:

- `input-required`
- `auth-required`
- `completed`
- `failed`
- `cancelled`

### Final states

These states represent terminal task completion:

- `completed`
- `failed`
- `cancelled`

### Aliases

The hub canonicalizes these declared aliases before frontend consumption:

- `input_required -> input-required`
- `auth_required -> auth-required`
- `canceled -> cancelled`
- `done -> completed`
- `success -> completed`
- `error -> failed`
- `rejected -> failed`

Unknown states are preserved as-is so providers can evolve without immediately breaking clients.
