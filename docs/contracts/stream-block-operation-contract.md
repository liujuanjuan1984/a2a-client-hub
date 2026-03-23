# Stream Block Operation Contract

This document defines the canonical block-operation contract used to unify
streaming updates, persisted history replay, and refresh projections.

## Goals

- Make append, replace, and finalize semantics explicit.
- Give authoritative updates a stable target block.
- Keep frontend reducers and backend projections on the same state machine.
- Push legacy heuristics into an adapter layer with a clear removal boundary.

## Canonical Event Shape

Each block update must be normalized to the following logical shape:

- `event_id`: Unique event identifier.
- `seq`: Monotonic message-local sequence number.
- `message_id`: Stable message identifier.
- `artifact_id`: Upstream artifact identifier when available.
- `block_id`: Stable logical block identifier.
- `lane_id`: Stable presentation lane identifier.
- `block_type`: One of `text`, `reasoning`, `tool_call`, `interrupt_event`.
- `op`: One of `append`, `replace`, `finalize`.
- `content`: Payload for `append` or `replace`. Empty for `finalize`.
- `base_seq`: Optional sequence used to reject stale authoritative updates.
- `is_finished`: Compatibility flag. Canonical semantics are driven by `op`.
- `source`: Diagnostic-only source hint.

## State Machine Rules

- `append`: Extend the existing block identified by `block_id`.
- `replace`: Replace the content of the existing block identified by `block_id`.
- `finalize`: Mark the existing block identified by `block_id` as finished without
  altering other blocks.

Consumers must not infer replace targets by searching for the "last text block".
Consumers must not infer duplicate removal from visible text content unless they
are running inside the legacy adapter.

## Lane Defaults

If `lane_id` is missing, adapters should derive a stable fallback:

- `text` -> `primary_text`
- `reasoning` -> `reasoning`
- `tool_call` -> `tool_call`
- `interrupt_event` -> `interrupt_event`

## Legacy Compatibility Rules

Legacy `artifact-update` payloads still rely on implicit semantics:

- `append=false`
- `source=final_snapshot`
- `source=finalize_snapshot`
- payload-local chunk ordering

Legacy adapters may map those signals to canonical operations:

- `append=true` -> `append`
- `append=false` or snapshot sources -> `replace`
- explicit canonical `op=finalize` -> `finalize`

Legacy overlap trimming and "rewrite latest text slot" behavior must remain in
adapter code only. Canonical reducers and projections should operate solely on
`block_id`, `lane_id`, `op`, and `base_seq`.
