# Artifact-First Interop Review

This note records the current evaluation for issue `#888`.

## Verdict

Issue `#888` is still a valid interoperability tracking item, but it is no longer a good framing for a Hub-side feature implementation task.

The current Hub backend already accepts artifact-first success streams and normalizes them into the canonical stream-block contract used by the frontend and history projection layers. In other words:

- the issue remains relevant as an ecosystem interoperability note
- it is not a current product blocker for `a2a-client-hub`
- it should not be reopened as a broad Hub-side behavior rewrite

## Why The Issue Still Exists

Both reviewed upstreams still emit successful streaming output primarily through `artifactUpdate` events and a terminal completed `statusUpdate`, instead of guaranteeing a user-facing `message` or `status.message` on the success path:

- `~/opencode-a2a-serve/src/opencode_a2a/execution/stream_runtime.py` emits streaming text chunks as `artifactUpdate`
- `~/opencode-a2a-serve/src/opencode_a2a/execution/coordinator.py` emits a final text artifact snapshot and then a completed `TaskStatusUpdateEvent` without a terminal status message
- `~/codex-a2a-serve/src/codex_a2a/execution/stream_processor.py` emits streaming chunks as `artifactUpdate`
- `~/codex-a2a-serve/src/codex_a2a/execution/response_emitter.py` emits a final text artifact snapshot and then a completed `TaskStatusUpdateEvent` without a terminal status message

That behavior is not automatically protocol-invalid, but it remains a real interoperability boundary for generic A2A chat clients that only render `message` or `status.message` as the primary visible answer.

## Why It Is Not A Hub Bug

The current Hub implementation already handles this boundary explicitly:

- `backend/app/features/invoke/hub_stream_contract.py` builds a canonical `streamBlock` even when the upstream only provides artifact text, with stable fallback identity and block metadata
- `backend/tests/invoke/test_a2a_invoke_service_stream_contract.py` verifies that artifact-only text payloads are normalized into the `primary_text` lane
- `backend/tests/sessions/test_session_hub_service_history.py` verifies that interleaved draft and final artifact text is collapsed into the final primary answer block for history replay
- `docs/contracts/stream-block-operation-contract.md` defines the canonical append/replace/finalize contract that keeps streaming, persistence, and replay on the same state machine

This matches the repository's current best-practice direction:

- absorb provider-specific wire variance in backend adapters
- expose a stable Hub-owned contract to frontend consumers
- avoid treating provider-private success-shape differences as a reason to fork frontend behavior

## Recommended Scope For `#888`

`#888` should stay as:

- an interoperability note
- a documentation and upstream-communication reference
- a place to record whether specific peers are safe for generic chat-style rendering without Hub-specific normalization

`#888` should not be used as:

- a catch-all implementation branch for stream rendering
- a reason to expand repo-local provider heuristics in the frontend
- a blocker for the current Hub stream pipeline

## Recommended Related Open Issues

The closest related open issue to develop alongside `#888` is `#866`.

Reason:

- `#866` already tracks ongoing OpenCode and Codex compatibility surfaces
- artifact-first success behavior is exactly the kind of peer-specific compatibility fact that belongs there
- any new diagnostics, review fixtures, or cleanup notes should likely be linked to `#866`

The second related issue is `#880`, but only when the branch expands into answer-selection semantics for mixed multipart or multi-artifact outputs.

Reason:

- `#880` is about the boundary between primary timeline content and attachment/detail material
- artifact-first output becomes more ambiguous when upstreams emit multiple artifacts or non-text parts
- if the branch stays focused on plain text artifact-first streams, `#880` should stay separate

Issue `#568` is adjacent but should only be bundled if the branch intentionally expands into broader consumer diagnostics or multipart review work.

## Implementation Guidance

If follow-up work is needed on top of this review, prefer one of the following narrow paths:

1. Add or refine English repository documentation that explains the artifact-first interoperability boundary.
2. Add diagnostics or review fixtures that make this boundary observable without changing the frontend contract.
3. Record upstream communication outcomes and sample payload facts, instead of adding new Hub-private rendering heuristics.

Avoid adding new frontend-side special cases for individual peer families unless a concrete regression demonstrates that the canonical backend contract is insufficient.
