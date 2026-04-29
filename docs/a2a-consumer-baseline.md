# A2A Consumer Baseline

This document defines the Hub consumer-side baseline introduced for issue `#873`.

The baseline is anchored to the `a2a-python` v1.0 consumer model, especially:

- `docs/migrations/v1_0/README.md`
- `src/a2a/extensions/common.py`
- `src/a2a/client/service_parameters.py`
- `src/a2a/server/routes/common.py`

## Goals

- Keep Hub aligned with core A2A v1.0 interoperability first.
- Treat extensions as declared capabilities plus request-scoped negotiation inputs.
- Prevent provider-private extension contracts from redefining whether a peer is fundamentally usable.
- Shrink Hub-private semantic wrapping to the thinnest protocol adaptation layer that still keeps the product operable.

## Consumer Layers

Hub should consume peer capabilities in this order:

1. Core interoperability
2. Declared extension capabilities
3. Request-scoped extension negotiation
4. Provider-private enhancement

### 1. Core Interoperability

The following checks determine whether a peer is basically usable as an A2A v1.0 peer:

- `supportedInterfaces` exists and contains at least one usable interface
- `protocolVersion` is compatible with A2A v1.0 expectations
- authentication requirements are understood
- transport reachability is acceptable for the selected binding

Failure at this layer is a real validation failure.

### 2. Declared Extension Capabilities

Extensions are first-class capability declarations published in the Agent Card.

Hub should:

- detect declared extension URIs
- normalize known URI aliases only when they preserve the same protocol meaning
- keep unsupported or unknown declarations visible as diagnostics
- avoid translating every declaration into a Hub-private contract family

Failure at this layer is usually diagnostic, not a hard interoperability failure.

### 3. Request-Scoped Extension Negotiation

When Hub depends on a declared extension for a given request, it should negotiate that dependency explicitly through standard request-scoped mechanisms.

Current baseline:

- use `A2A-Extensions` as the standard request header for extension negotiation
- merge requested extension URIs with any pre-existing outbound headers
- request only the extensions needed for the active operation

This keeps Hub closer to the standard client behavior shown in `a2a-python`, where requested extensions are attached per request instead of being treated as a static global schema decision.

### 4. Provider-Private Enhancement

Provider-private extensions may enhance the experience, but they must not redefine basic peer validity.

Hub should treat provider-private contracts as:

- optional enhancements
- capability-specific diagnostics
- runtime negotiation inputs when they are declared and intentionally consumed

Hub should not treat missing provider-private details as proof that the peer is not a usable A2A v1.0 peer.

## Minimal Adapter Boundary

Hub may keep a thin adaptation layer, but only for protocol wiring.

Allowed:

- routing standard A2A payloads into Hub runtime entrypoints
- normalizing known standard URI aliases
- attaching request-scoped extension negotiation headers
- applying a small number of compatibility fixes when they preserve the same protocol semantics

Not allowed:

- inventing a Hub-private semantic family that upstream peers must target
- rewrapping provider-private contracts into a long-lived Hub-private taxonomy
- rebuilding extension capability declaration into a Hub-owned static schema regime
- keeping heavy compatibility abstractions that exist only to preserve one upstream's private design

## `card:validate` Responsibility

`card:validate` should answer:

- Is this peer basically interoperable as an A2A v1.0 peer?
- Which extensions are declared?
- Which declared extensions are consumable by Hub?
- Which contracts are invalid, unsupported, or enhancement-only?

`card:validate` should not:

- default provider-private extension gaps to overall peer invalidity
- collapse core interoperability and extension diagnostics into one failure bucket
- require every enhancement contract to be losslessly mapped before the peer can be considered valid

## Current Repository Implications

The first implementation step in this repository is:

- define validation success from core interoperability only
- keep extension contract problems visible as warnings or diagnostics
- start issuing request-scoped `A2A-Extensions` headers on extension JSON-RPC calls

Further refactors can then reduce remaining Hub-private normalization layers without losing observable behavior.
