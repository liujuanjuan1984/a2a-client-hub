"""Canonical runtime status contract for A2A stream events."""

from __future__ import annotations

from typing import Final

RUNTIME_STATUS_CONTRACT_VERSION: Final[str] = "v1"

CANONICAL_RUNTIME_STATES: Final[tuple[str, ...]] = (
    "working",
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
)

TERMINAL_STREAM_RUNTIME_STATES: Final[tuple[str, ...]] = (
    "input-required",
    "auth-required",
    "completed",
    "failed",
    "cancelled",
)

FINAL_RUNTIME_STATES: Final[tuple[str, ...]] = (
    "completed",
    "failed",
    "cancelled",
)

INTERACTIVE_RUNTIME_STATES: Final[tuple[str, ...]] = (
    "input-required",
    "auth-required",
)

FAILURE_RUNTIME_STATES: Final[tuple[str, ...]] = (
    "failed",
    "cancelled",
)

RUNTIME_STATUS_ALIASES: Final[dict[str, str]] = {
    "input_required": "input-required",
    "auth_required": "auth-required",
    "canceled": "cancelled",
    "done": "completed",
    "success": "completed",
    "error": "failed",
    "rejected": "failed",
}

NORMALIZED_RUNTIME_STATUS_ALIASES: Final[dict[str, str]] = {
    alias.strip().lower().replace("_", "-"): canonical
    for alias, canonical in RUNTIME_STATUS_ALIASES.items()
}


def _strip_task_state_prefix(value: str) -> str:
    if value.startswith("task-state-"):
        return value[len("task-state-") :]
    return value


def normalize_runtime_state(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _strip_task_state_prefix(value.strip().lower().replace("_", "-"))
    if not normalized:
        return None
    return NORMALIZED_RUNTIME_STATUS_ALIASES.get(normalized, normalized)


def is_interactive_runtime_state(value: str | None) -> bool:
    normalized = normalize_runtime_state(value)
    return normalized in INTERACTIVE_RUNTIME_STATES


def runtime_status_contract_payload() -> dict[str, object]:
    return {
        "version": RUNTIME_STATUS_CONTRACT_VERSION,
        "canonicalStates": list(CANONICAL_RUNTIME_STATES),
        "terminalStates": list(TERMINAL_STREAM_RUNTIME_STATES),
        "finalStates": list(FINAL_RUNTIME_STATES),
        "interactiveStates": list(INTERACTIVE_RUNTIME_STATES),
        "failureStates": list(FAILURE_RUNTIME_STATES),
        "aliases": dict(RUNTIME_STATUS_ALIASES),
        "passthroughUnknown": True,
    }


def terminal_runtime_state_values() -> frozenset[str]:
    alias_states = {
        alias
        for alias, canonical in RUNTIME_STATUS_ALIASES.items()
        if canonical in TERMINAL_STREAM_RUNTIME_STATES
    }
    normalized_alias_states = {
        alias
        for alias, canonical in NORMALIZED_RUNTIME_STATUS_ALIASES.items()
        if canonical in TERMINAL_STREAM_RUNTIME_STATES
    }
    prefixed_states = {
        f"task-state-{state}" for state in TERMINAL_STREAM_RUNTIME_STATES
    }
    prefixed_alias_states = {
        f"task-state-{alias}" for alias in (*alias_states, *normalized_alias_states)
    }
    return frozenset(
        (
            *TERMINAL_STREAM_RUNTIME_STATES,
            *alias_states,
            *normalized_alias_states,
            *prefixed_states,
            *prefixed_alias_states,
        )
    )
