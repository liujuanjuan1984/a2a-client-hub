from __future__ import annotations

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
