"""HTTP status code mapping for A2A-facing error codes."""

from __future__ import annotations

from typing import Final, final


@final
class _A2AErrorCodeStatus:
    """Centralized error-code -> HTTP status mapping."""

    # 4xx fail-fast
    _STATUS_BY_ERROR_CODE: Final[dict[str, int]] = {
        "session_not_found": 404,
        "outbound_not_allowed": 403,
        "not_supported": 400,
        "method_not_supported": 400,
        "extension_contract_error": 400,
        "invalid_conversation_id": 400,
        "runtime_invalid": 400,
        "invalid_request": 400,
        "invalid_query": 400,
        # client-side coordination
        "invoke_inflight": 409,
        # upstream-related
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
