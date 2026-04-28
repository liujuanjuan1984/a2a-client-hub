# Stream Block Operation Contract

This document defines the canonical block-operation contract used to unify streaming updates, persisted history replay, and refresh projections.

## Goals

- Make append, replace, and finalize semantics explicit.
- Give authoritative updates a stable target block.
- Keep frontend reducers and backend projections on the same state machine.
- Reject non-canonical stream payloads at the boundary.

## Canonical Event Shape

Each block update must be normalized to the following logical shape:

- `eventId`: Unique event identifier.
- `seq`: Monotonic message-local sequence number.
- `messageId`: Stable message identifier.
- `artifactId`: Upstream artifact identifier when available.
- `blockId`: Stable logical block identifier.
- `laneId`: Stable presentation lane identifier.
- `blockType`: One of `text`, `reasoning`, `tool_call`, `interrupt_event`.
- `op`: One of `append`, `replace`, `finalize`.
- `content`: Payload for `append` or `replace`. Empty for `finalize`.
- `baseSeq`: Optional sequence used to reject stale authoritative updates.
- `isFinished`: Compatibility flag. Canonical semantics are driven by `op`.
- `source`: Diagnostic-only source hint.

## State Machine Rules

- `append`: Extend the existing block identified by `blockId`.
- `replace`: Replace the content of the existing block identified by `blockId`.
- `finalize`: Mark the existing block identified by `blockId` as finished without altering other blocks.

Consumers must not infer replace targets by searching for the "last text block". Consumers must not infer duplicate removal from visible text content.

## Completion Acknowledgement

Canonical streaming consumers must use an explicit persisted-completion acknowledgement as the only success-finalization signal.

When the server has finished durable persistence for the current message, it may emit a terminal `statusUpdate` carrying:

- `metadata.shared.stream.completionPhase = "persisted"`
- `metadata.shared.stream.messageId = <canonical message id>`

This acknowledgement is emitted after persistence succeeds and before any transport-level `stream_end` marker. Consumers may finalize the live message and refresh history as soon as they observe this persisted ack.

Transport completion alone (`stream_end` / `onDone`) must not be treated as a successful completion signal. If the transport closes before this ack arrives, consumers should surface the stream as interrupted or protocol-invalid.

## Lane Defaults

If `laneId` is missing, canonical normalization should derive a stable fallback:

- `text` -> `primary_text`
- `reasoning` -> `reasoning`
- `tool_call` -> `tool_call`
- `interrupt_event` -> `interrupt_event`

## Canonical-Only Boundary

Canonical streaming reducers and projections must operate solely on `blockId`, `laneId`, `op`, and `baseSeq`.

Adapters must reject or drop non-canonical payloads that rely on implicit overwrite semantics, snapshot source hints, or legacy snake_case stream metadata. The only supported overwrite/finalization semantics are explicit `op="replace"` and `op="finalize"`.
