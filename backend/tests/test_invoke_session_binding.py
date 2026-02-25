from __future__ import annotations

from app.services.invoke_session_binding import (
    is_recoverable_invoke_session_error,
    normalize_error_code,
    status_code_for_invoke_session_error,
    ws_error_code_for_invoke_session_error,
    ws_error_code_for_recovery_failed,
)


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
