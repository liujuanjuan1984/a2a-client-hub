# Codex Discovery Watch Design

This document captures the recommended semantics and integration boundary for
`codex.discovery.watch`.

It is intentionally a design artifact, not a production implementation plan for
the current PR. The goal is to avoid treating `watch` as a trivial extension of
the existing list/read APIs.

## Problem Statement

`codex.discovery.skills.list`, `codex.discovery.apps.list`,
`codex.discovery.plugins.list`, and `codex.discovery.plugins.read` fit a
request/response model. `codex.discovery.watch` does not.

If the Hub eventually consumes `watch`, it must answer questions that do not
exist for list/read:

- Is the upstream surface a long-lived subscription, a polling trigger, or a
  one-shot invalidation signal?
- What is the source of truth for discovery data after a watch event?
- How should frontend cache invalidation, background refresh, reconnect, and
  stale windows behave?
- Should watch belong to the main chat/runtime transport path or remain a
  separate discovery synchronization surface?

## Goals

- Define a safe integration model before any production watch implementation.
- Keep list/read as the stable source of truth for discovery payloads.
- Avoid over-coupling discovery refresh to the chat runtime lifecycle.
- Minimize false precision when upstream watch payloads are incomplete,
  reordered, dropped, or duplicated.

## Non-Goals

- No production watch endpoint in this phase.
- No frontend live-update implementation in this phase.
- No attempt to merge upstream deltas into Hub-owned canonical discovery state
  without a refresh.

## Recommended Design

### 1. Treat watch as an invalidation channel, not as canonical data

The first Hub-consumed version of `codex.discovery.watch` should be modeled as a
signal that existing discovery queries may be stale.

Recommended rule:

- `watch` tells the client _that something changed_.
- `list/read` remain the only authoritative data retrieval surfaces.
- A watch event should cause a targeted refetch or invalidation, not a direct
  cache patch by default.

This keeps the Hub contract stable even when upstream watch payloads are sparse
or provider-specific.

### 2. Keep watch outside the main chat/runtime stream pipeline

`watch` should not be folded into the main chat message stream, task runtime
state stream, or interrupt lifecycle.

Recommended boundary:

- Chat runtime streams remain scoped to message/task execution.
- Discovery watch is a separate synchronization concern.
- The frontend should bind watch to React Query invalidation or refetch logic,
  not to chat transcript rendering.

This avoids mixing unrelated failure domains and retry policies.

### 3. Use coarse invalidation semantics before any delta-merge semantics

The Hub should not attempt to merge item-level patches from the upstream watch
surface in the first implementation phase.

Recommended behavior:

- A watch event invalidates one or more cached discovery collections.
- The client performs a normal list/read refresh.
- If the upstream later proves to emit versioned, lossless deltas, delta
  handling can be added as a later phase behind an explicit protocol revision.

### 4. Prefer server-side normalization of watch scopes

If the upstream emits provider-specific watch payloads, the Hub should normalize
them into a small set of invalidation scopes such as:

- `skills`
- `apps`
- `plugins`
- `plugin:{id}`
- `all`

The frontend should not depend on raw upstream watch event shapes.

## Not Recommended

The following approaches should be avoided in the first implementation phase:

- Exposing a raw upstream watch channel directly to the browser.
- Treating watch events as authoritative item mutations without a follow-up
  refresh.
- Attaching watch lifecycle to an active chat session or task stream.
- Building a Hub-owned merge engine for unordered upstream deltas before the
  protocol proves it can support lossless replay/versioning.
- Making frontend rendering correctness depend on never-missed watch events.

## Failure and Reconnect Semantics

If the Hub later implements watch, the recommended client behavior is:

1. Open the watch channel only while the discovery UI is active or when the
   product explicitly opts into background freshness.
2. On every valid watch event, invalidate the relevant React Query keys.
3. On disconnect, mark the watch channel stale and fall back to periodic
   foreground refetch or on-focus refetch.
4. On reconnect, perform at least one full discovery refresh before trusting
   subsequent watch events.
5. If the upstream cannot provide a monotonic version/cursor, assume missed
   events are possible and always prefer a full refetch after reconnect.

## Suggested State Model

The minimal state machine should be:

- `idle`: watch not active
- `connecting`: watch setup in progress
- `active`: watch channel established
- `stale`: disconnected or heartbeat gap exceeded; cached data may be outdated
- `refreshing`: follow-up list/read refresh in progress after invalidation
- `failed`: repeated setup/reconnect failure exceeded policy

Important rule:

- `active` does not imply the local cache is authoritative forever.
- `stale` should trigger conservative refresh behavior, not silent degradation.

## React Query Integration

Recommended frontend behavior:

- Keep list/read data in standard React Query caches.
- Map watch events to `invalidateQueries` for:
  - `skills`
  - `apps`
  - `plugins`
  - `plugin:{id}`
- Continue to use explicit list/read hooks for the actual data fetches.
- Do not store watch payloads as the canonical discovery payload in the query
  cache.

This aligns with the existing frontend architecture better than inventing a
parallel cache system for discovery.

## Backend Integration Boundary

If the Hub later implements watch, the backend should own:

- Upstream watch transport handling
- Scope normalization
- Retry/backoff policy for the upstream watch channel
- Staleness detection and reconnect semantics
- Security and outbound policy checks

The frontend should own:

- Query invalidation
- Refetch orchestration
- UI state for `connecting`, `active`, `stale`, and `failed`

## Recommendation

`codex.discovery.watch` is worth pursuing only if the product needs freshness
that list/read plus focus/manual refresh cannot provide.

The recommended next implementation phase is not a full production watch
feature. It should start as:

1. A backend PoC that normalizes upstream watch signals into invalidation
   scopes.
2. A frontend integration that invalidates React Query caches and refetches
   list/read data.
3. A decision gate before any delta-merge or background-always-on behavior.

## Decision

Recommended decision for the current repository state:

- Do not implement production `codex.discovery.watch` yet.
- Treat this design as the boundary document for any future watch work.
- If implementation proceeds, create a dedicated follow-up issue for a
  backend-first invalidation PoC rather than mixing it into list/read or chat
  runtime work.
