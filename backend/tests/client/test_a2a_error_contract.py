from __future__ import annotations

from app.api.error_codes import (
    status_code_for_extension_error_code,
    status_code_for_invoke_error_code,
)
from app.integrations.a2a_client.errors import A2APeerProtocolError
from app.integrations.a2a_error_contract import (
    build_protocol_error_from_jsonrpc_error,
    build_upstream_error_details_from_protocol_error,
    map_upstream_error_code,
)


def test_map_upstream_error_code_prefers_standard_jsonrpc_mapping() -> None:
    assert (
        map_upstream_error_code(
            jsonrpc_code=-32601,
            message="Method not found",
            default_error_code="upstream_error",
        )
        == "method_not_supported"
    )


def test_build_protocol_error_from_jsonrpc_error_prefers_error_data_type() -> None:
    error = build_protocol_error_from_jsonrpc_error(
        {
            "code": -32001,
            "message": "Session is missing",
            "data": {"type": "session-not-found"},
        },
        fallback_message="fallback",
        http_status=400,
    )

    assert error.error_code == "session_not_found"
    assert error.code == -32001


def test_build_protocol_error_from_jsonrpc_error_normalizes_uppercase_wire_types() -> (
    None
):
    error = build_protocol_error_from_jsonrpc_error(
        {
            "code": -32003,
            "message": "Upstream rejected the request",
            "data": {"type": "UPSTREAM_UNAUTHORIZED"},
        },
        fallback_message="fallback",
        http_status=401,
    )

    assert error.error_code == "upstream_unauthorized"
    assert error.code == -32003


def test_map_upstream_error_code_normalizes_uppercase_fine_grained_wire_types() -> None:
    assert (
        map_upstream_error_code(
            data={"type": "UPSTREAM_PERMISSION_DENIED"},
            default_error_code="upstream_error",
        )
        == "upstream_permission_denied"
    )
    assert (
        map_upstream_error_code(
            data={"type": "UPSTREAM_QUOTA_EXCEEDED"},
            default_error_code="upstream_error",
        )
        == "upstream_quota_exceeded"
    )


def test_build_upstream_error_details_from_protocol_error_extracts_missing_params() -> (
    None
):
    details = build_upstream_error_details_from_protocol_error(
        A2APeerProtocolError(
            "project_id/channel_id required",
            error_code="peer_protocol_error",
            rpc_code=-32602,
            data={"missing_params": ["project_id", "channel_id"]},
        ),
        default_error_code="upstream_stream_error",
    )

    assert details.error_code == "invalid_params"
    assert details.source == "upstream_a2a"
    assert details.jsonrpc_code == -32602
    assert details.missing_params == (
        {"name": "project_id", "required": True},
        {"name": "channel_id", "required": True},
    )
    assert details.upstream_error == {
        "message": "project_id/channel_id required",
        "data": {"missing_params": ["project_id", "channel_id"]},
    }


def test_status_code_for_extension_error_code_supports_fine_grained_upstream_codes() -> (
    None
):
    assert status_code_for_extension_error_code("upstream_bad_request") == 400
    assert status_code_for_extension_error_code("upstream_unauthorized") == 401
    assert status_code_for_extension_error_code("upstream_permission_denied") == 403
    assert status_code_for_extension_error_code("upstream_resource_not_found") == 404
    assert status_code_for_extension_error_code("upstream_quota_exceeded") == 429
    assert status_code_for_invoke_error_code("upstream_server_error") == 502
