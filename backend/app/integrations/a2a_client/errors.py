"""Shared exception types for the A2A integration layer."""


class A2AAgentUnavailableError(RuntimeError):
    """Raised when a downstream A2A agent cannot be reached in time."""
    error_code = "agent_unavailable"


class A2AOutboundNotAllowedError(A2AAgentUnavailableError):
    """Raised when an outbound A2A URL is blocked by the allowlist."""
    error_code = "outbound_not_allowed"


class A2AClientResetRequiredError(A2AAgentUnavailableError):
    """Raised when a cached A2A client should be torn down and recreated."""
    error_code = "agent_unavailable"


__all__ = [
    "A2AAgentUnavailableError",
    "A2AOutboundNotAllowedError",
    "A2AClientResetRequiredError",
]
