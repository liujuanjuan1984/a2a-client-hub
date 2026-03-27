"""HTTP status code mapping for A2A-facing error codes."""

from __future__ import annotations

from typing import Final, final


@final
class _A2AErrorCodeStatus:
    """Centralized error-code -> HTTP status mapping."""

    # 4xx fail-fast
    _STATUS_BY_ERROR_CODE: Final[dict[str, int]] = {
        "session_not_found": 404,
        "session_forbidden": 403,
        "outbound_not_allowed": 403,
        "not_supported": 400,
        "method_not_supported": 400,
        "method_not_found": 400,
        "extension_contract_error": 400,
        "invalid_conversation_id": 400,
        "runtime_invalid": 400,
        "invalid_request": 400,
        "invalid_params": 400,
        "invalid_query": 400,
        "method_disabled": 403,
        "interrupt_request_not_found": 404,
        "interrupt_request_expired": 409,
        "interrupt_type_mismatch": 409,
        # client-side coordination
        "invoke_inflight": 409,
        # upstream-related
        "upstream_bad_request": 400,
        "upstream_unauthorized": 401,
        "upstream_permission_denied": 403,
        "upstream_resource_not_found": 404,
        "upstream_quota_exceeded": 429,
        "upstream_client_error": 502,
        "upstream_server_error": 502,
        "upstream_unreachable": 503,
        "upstream_http_error": 502,
        "upstream_error": 502,
        "upstream_payload_error": 502,
        "agent_unavailable": 503,
        "timeout": 504,
        "client_reset": 502,
    }

    @classmethod
    def status_for_extension_error_code(
        cls,
        error_code: str | None,
        *,
        default_status: int = 502,
    ) -> int:
        if not error_code:
            return default_status
        return cls._STATUS_BY_ERROR_CODE.get(error_code, default_status)

    @classmethod
    def status_for_invoke_error_code(
        cls,
        error_code: str | None,
        *,
        default_status: int = 502,
    ) -> int:
        if not error_code:
            return default_status
        return cls._STATUS_BY_ERROR_CODE.get(error_code, default_status)


status_code_for_extension_error_code = (
    _A2AErrorCodeStatus.status_for_extension_error_code
)
status_code_for_invoke_error_code = _A2AErrorCodeStatus.status_for_invoke_error_code

__all__ = [
    "status_code_for_extension_error_code",
    "status_code_for_invoke_error_code",
]
