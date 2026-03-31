# Compatibility Notes and Non-Goals

This document explains how `a2a-client-hub` positions itself in the A2A and coding-agent ecosystem.

It exists to make two things explicit:

- what kinds of peers the Hub currently targets and exercises most heavily
- what the project does **not** try to be

## Positioning

`a2a-client-hub` is an A2A client/control plane.

It is intended to sit between human users and one or more downstream A2A agents, providing governance, continuity, and a stable product surface across web and mobile.

It is not:

- an A2A provider implementation
- an MCP server
- an MCP registry
- an MCP gateway or MCP management plane

The project follows the A2A view that A2A and MCP solve different layers of the stack: MCP is typically used inside an agent, while A2A is used between agents.

## Compatibility Framing

The Hub does not treat every A2A peer as feature-equivalent.

Current support is best understood in tiers:

The validated peer profiles listed below are maintained compatibility notes, not an exhaustive allowlist of every peer that could work.

### 1. First-Class Hub Compatibility

These peers are the best fit for the current product surface:

- standard A2A Agent Card support
- invoke and streaming support
- shared session continuity / query support consumed by the Hub
- shared interrupt callback / recovery support consumed by the Hub

This tier is where the repository currently spends most of its compatibility effort.

### 2. Validated Peer Profiles

The following peer profiles are explicitly part of the current target audience:

- OpenCode-compatible A2A peers
- Codex-family A2A peers that publish a compatible Agent Card and the Hub-used session / interrupt capabilities
- other coding-agent peers that follow the same compatible A2A surface

OpenCode appears frequently in examples because it is one of the most deeply exercised profiles in the current codebase. That should not be read as "OpenCode only".

### 3. Partial Compatibility

Some peers may still work for narrower use cases even if they do not expose the full shared extension surface used by the Hub.

Typical examples:

- invoke-only peers
- stream-capable peers without session-query extensions
- peers that are standard enough for transport-level interoperability but do not provide the continuity workflows expected by the Hub UI

For these peers, the Hub may still support onboarding, invocation, and basic streaming while feature depth is reduced.

## Why Provider-Specific Examples Still Exist

Several docs and examples still use OpenCode-flavored extension URIs, metadata, or method names.

That is a reflection of current exercised compatibility profiles, not a claim that the Hub only works with OpenCode.

The intended contract boundary is:

- Hub-facing routes and UI should stay provider-agnostic where practical
- provider-specific wire details should remain behind compatibility layers
- docs should clearly separate generic Hub behavior from profile-specific notes

## Maintained Non-Goals

The project does not currently aim to:

- become an MCP platform
- expose a generic MCP tool marketplace
- claim universal feature parity across all A2A peers
- hide the fact that some advanced workflows depend on peer-declared extensions

## Documentation Rule

When adding new docs or examples:

- prefer generic Hub terminology first
- keep provider-specific examples clearly labeled
- avoid implying that one exercised profile equals the entire compatibility set
