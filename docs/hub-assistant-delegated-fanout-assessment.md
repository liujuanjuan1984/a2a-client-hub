# Hub Assistant Delegated Fan-Out Assessment

This document records the implementation assessment for issue #819.

## Current Status

Issue #819 remains valid, but it should stay a design and sequencing item for
now. The current implementation intentionally keeps delegated batch handling
serial while preserving bounded scope:

- `hub_assistant.sessions.send_message` accepts 1 to 10 conversation ids.
- `hub_assistant.agents.start_sessions` accepts 1 to 10 agent ids.
- Each accepted target creates a durable `delegated_invoke` task.
- Accepted target conversations are added to durable follow-up tracking.
- The task dispatcher claims a batch of due tasks, then executes the claimed
  tasks serially.

The current serial behavior is still appropriate for the existing `max_length=10`
tool limits. It keeps authorization, handoff message persistence, task enqueueing,
and follow-up tracking easy to reason about.

## Code Map

- `backend/app/features/hub_access/operation_registry.py`
  defines the tool input limits and write-confirmation policy.
- `backend/app/features/hub_assistant/shared/delegated_conversation_service.py`
  handles target authorization, handoff message persistence, durable task
  enqueueing, and follow-up tracking for delegated handoffs.
- `backend/app/features/hub_assistant/shared/task_service.py`
  persists and claims `delegated_invoke`, permission-continuation, and follow-up
  tasks.
- `backend/app/features/hub_assistant/shared/task_job.py`
  executes claimed Hub Assistant tasks.
- `backend/app/core/config.py`
  defines `HUB_ASSISTANT_TASK_BATCH_SIZE`,
  `HUB_ASSISTANT_TASK_POLL_INTERVAL_SECONDS`, and
  `HUB_ASSISTANT_TASK_RUNNING_TIMEOUT_SECONDS`.

## Assessment

The issue is still reasonable because the current system has two serial fan-out
points:

1. The tool entrypoints serially authorize each target, record the handoff, create
   durable tasks, and update follow-up tracking.
2. The durable task job serially executes every claimed `delegated_invoke` task.

However, a direct `asyncio.gather` conversion inside either path would not match
the current codebase's best practices. The implementation uses SQLAlchemy async
sessions, per-target authorization, committed handoff records, durable task
status transitions, and external A2A calls. Those boundaries need an explicit
concurrency contract before parallel execution is introduced.

## Recommended Direction

Keep the current product behavior serial until the orchestration contract is more
explicit. When fan-out is implemented, prefer a windowed durable-dispatch model:

- Keep the tool entrypoint mostly serial for authorization, audit-shaped handoff
  recording, task enqueueing, and follow-up tracking.
- Add a configurable, low default concurrency window to the durable task
  dispatcher instead of making the tool call wait on parallel upstream work.
- Execute each concurrent task with its own database session and avoid sharing a
  single `AsyncSession` across concurrent branches.
- Preserve per-target task status and make the batch/group aggregate derived from
  per-target outcomes.
- Avoid canceling sibling targets when one target fails, times out, or needs
  credential repair.
- Keep stable target ordering in returned payloads and persisted run summaries,
  even if execution completes out of order.

This direction preserves the current handoff semantics while reducing the
eventual wall-clock cost of many delegated targets.

## Contract Boundaries

### Approval and Audit

Approval should remain at the write operation boundary with the validated target
list and message. Concurrency must not bypass `HubOperationGateway.authorize`.

Audit and persisted handoff records should remain target-specific enough to
answer which target received which delegated message. If a batch-level id is
added, it should supplement per-target records rather than replace them.

### Idempotency

The current delegated task enqueue path does not assign a per-target dedupe key.
Before parallel dispatch or retry behavior is expanded, each delegated target
should have a stable idempotency key derived from the Hub Assistant conversation,
operation or batch id, target kind, target id, and message identity.

This is especially important because stale running tasks can be recovered and
retried after `HUB_ASSISTANT_TASK_RUNNING_TIMEOUT_SECONDS`.

### Failure, Timeout, Cancellation, and Interrupts

Future fan-out should aggregate results with per-target states such as accepted,
running, completed, failed, timed out, canceled, and waiting for approval. A
single target failure should not erase successful sibling outcomes.

Interrupt recovery should remain tied to the target conversation and persisted
message anchors. The batch aggregate should point to target-level recovery state
instead of becoming a separate recovery authority.

## Related Issues

Recommended nearby issue handling:

- #845 should land before or alongside any non-trivial fan-out implementation
  because a plan contract gives batch steps stable ids and operation references.
- #846 should land before real parallel dispatch because persisted run and step
  state is the cleanest place to expose partial completion and failure.
- #847 is highly related to the execution loop, but it explicitly excludes
  fan-out. Keep it separate unless the branch is intentionally scoped as a larger
  orchestration slice.
- #848 is the long-term execution-facts epic. It should influence the design, but
  it is too broad to bundle into #819.

No other currently open issue should be bundled directly into this branch. The
closest practical sequencing is #845, then #846, then a constrained #819
implementation.

## Regression Strategy for a Future Implementation

A future implementation should include backend tests for:

- bounded concurrency and stable result ordering;
- per-target authorization still being required;
- one target failure not canceling siblings;
- timeout handling and stale running task recovery;
- no shared `AsyncSession` usage across concurrent task branches;
- idempotent retry behavior for recovered delegated tasks;
- follow-up tracking after mixed accepted and failed targets.

Frontend tests are not required unless the implementation changes visible batch
or run-state rendering.
