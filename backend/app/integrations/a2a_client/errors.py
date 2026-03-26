"""Shared exception types for the A2A integration layer."""


class A2AAgentUnavailableError(RuntimeError):
    """Raised when a downstream A2A agent cannot be reached in time."""

    error_code = "agent_unavailable"


class A2AUpstreamTimeoutError(A2AAgentUnavailableError):
    """Raised when a downstream A2A agent times out before responding."""

    error_code = "timeout"


class A2AOutboundNotAllowedError(A2AAgentUnavailableError):
    """Raised when an outbound A2A URL is blocked by the allowlist."""

    error_code = "outbound_not_allowed"


class A2AClientResetRequiredError(A2AAgentUnavailableError):
    """Raised when a cached A2A client should be torn down and recreated."""

    error_code = "agent_unavailable"


class A2AUnsupportedBindingError(A2AAgentUnavailableError):
    """Raised when no supported adapter matches the peer declaration."""


class A2AUnsupportedOperationError(A2AAgentUnavailableError):
    """Raised when a peer does not implement an optional operation."""

    error_code = "unsupported_operation"


class A2AStreamingNotSupportedError(A2AUnsupportedOperationError):
    """Raised when the selected adapter cannot stream for this peer."""

    error_code = "streaming_not_supported"


class A2APeerProtocolError(A2AAgentUnavailableError):
    """Raised when the downstream peer violates or rejects the active protocol."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "peer_protocol_error",
        rpc_code: int | None = None,
        http_status: int | None = None,
        data: object | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.code = rpc_code
        self.http_status = http_status
        self.data = data


__all__ = [
    "A2AAgentUnavailableError",
    "A2AOutboundNotAllowedError",
    "A2AClientResetRequiredError",
    "A2APeerProtocolError",
    "A2AStreamingNotSupportedError",
    "A2AUpstreamTimeoutError",
    "A2AUnsupportedBindingError",
    "A2AUnsupportedOperationError",
]
