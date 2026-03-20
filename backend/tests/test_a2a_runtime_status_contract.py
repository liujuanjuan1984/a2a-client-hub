from __future__ import annotations

from app.integrations.a2a_runtime_status_contract import (
    is_interactive_runtime_state,
    normalize_runtime_state,
    runtime_status_contract_payload,
    terminal_runtime_state_values,
)


def test_normalize_runtime_state_maps_declared_aliases() -> None:
    assert normalize_runtime_state("input_required") == "input-required"
    assert normalize_runtime_state("canceled") == "cancelled"
    assert normalize_runtime_state("success") == "completed"
    assert normalize_runtime_state("working") == "working"


def test_runtime_status_contract_payload_declares_v1_contract() -> None:
    payload = runtime_status_contract_payload()

    assert payload["version"] == "v1"
    assert payload["canonicalStates"] == [
        "working",
        "input-required",
        "auth-required",
        "completed",
        "failed",
        "cancelled",
    ]
    assert payload["terminalStates"] == [
        "input-required",
        "auth-required",
        "completed",
        "failed",
        "cancelled",
    ]
    assert payload["passthroughUnknown"] is True


def test_terminal_runtime_state_values_include_aliases() -> None:
    values = terminal_runtime_state_values()

    assert "input-required" in values
    assert "auth-required" in values
    assert "input_required" in values
    assert "auth_required" in values
    assert "canceled" in values
    assert "rejected" in values


def test_is_interactive_runtime_state_accepts_declared_aliases() -> None:
    assert is_interactive_runtime_state("input_required") is True
    assert is_interactive_runtime_state("auth_required") is True
    assert is_interactive_runtime_state("working") is False
