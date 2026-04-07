from __future__ import annotations

import pytest

from app.features.invoke.session_binding import (
    is_recoverable_invoke_session_error,
    normalize_error_code,
    resolve_invoke_session_control_intent,
    status_code_for_invoke_session_error,
    ws_error_code_for_invoke_session_error,
    ws_error_code_for_recovery_failed,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest


def test_normalize_error_code_rejects_invalid_inputs() -> None:
    assert normalize_error_code(" Session-Not-Found ") == "session_not_found"
    assert normalize_error_code(None) == ""


def test_is_recoverable_invoke_session_error_normalizes_case_and_separator() -> None:
    assert is_recoverable_invoke_session_error("Session_Not_Found")
    assert is_recoverable_invoke_session_error(" SESSION-NOT-FOUND ")


def test_ws_error_code_for_recovery_failed_normalizes_and_maps_session_not_found() -> (
    None
):
    assert (
        ws_error_code_for_recovery_failed(" Session-Not-Found ")
        == "session_not_found_recovery_exhausted"
    )


def test_ws_error_code_for_recovery_failed_normalizes_unknown_code_to_normalized_value() -> (
    None
):
    assert ws_error_code_for_recovery_failed("UPPER-CASE") == "upper_case"


def test_status_code_and_http_error_mapping_normalizes_inputs() -> None:
    assert status_code_for_invoke_session_error(" SESSION_NOT_FOUND ") == 404
    assert (
        ws_error_code_for_invoke_session_error(" SESSION-NOT-FOUND ")
        == "session_not_found"
    )
    assert status_code_for_invoke_session_error("idempotency_conflict") == 409
    assert (
        ws_error_code_for_invoke_session_error("idempotency_conflict")
        == "idempotency_conflict"
    )
    assert status_code_for_invoke_session_error("message_id_conflict") == 409
    assert (
        ws_error_code_for_invoke_session_error("message_id_conflict")
        == "message_id_conflict"
    )
    assert status_code_for_invoke_session_error("invoke_interrupt_failed") == 409
    assert (
        ws_error_code_for_invoke_session_error("invoke_interrupt_failed")
        == "invoke_interrupt_failed"
    )
    assert (
        ws_error_code_for_invoke_session_error("invalid_message_id")
        == "invalid_message_id"
    )
    assert status_code_for_invoke_session_error("append_requires_bound_session") == 409
    assert status_code_for_invoke_session_error("append_unavailable") == 409
    assert (
        ws_error_code_for_invoke_session_error("append_unavailable")
        == "append_unavailable"
    )


def test_resolve_invoke_session_control_intent_prefers_explicit_contract() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "sessionControl": {"intent": "append"},
            "metadata": {"extensions": {"interrupt": True}},
        }
    )

    assert resolve_invoke_session_control_intent(payload) == "append"


def test_resolve_invoke_session_control_intent_supports_legacy_interrupt_metadata() -> (
    None
):
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "metadata": {"extensions": {"interrupt": True}},
        }
    )

    assert resolve_invoke_session_control_intent(payload) == "preempt"


def test_invoke_request_allows_empty_query_for_preempt_only_session_control() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "",
            "conversationId": "conv-1",
            "sessionControl": {"intent": "preempt"},
        }
    )

    assert payload.query == ""


def test_invoke_request_rejects_empty_query_without_preempt_session_control() -> None:
    with pytest.raises(ValueError, match="query must not be empty"):
        A2AAgentInvokeRequest.model_validate(
            {
                "query": "   ",
                "conversationId": "conv-1",
            }
        )
