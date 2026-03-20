# A2A Error And Runtime Status Contract

This repository treats upstream A2A protocol data as two separate layers:

- `error_code`: Hub canonical business semantic used by UI, HTTP status mapping, and stable client logic
- `jsonrpc_code`: raw upstream JSON-RPC numeric code preserved for diagnostics and advanced recovery

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
