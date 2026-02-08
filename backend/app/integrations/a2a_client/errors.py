"""Shared exception types for the A2A integration layer."""


class A2AAgentUnavailableError(RuntimeError):
    """Raised when a downstream A2A agent cannot be reached in time."""


class A2AClientResetRequiredError(A2AAgentUnavailableError):
    """Raised when a cached A2A client should be torn down and recreated."""


__all__ = ["A2AAgentUnavailableError", "A2AClientResetRequiredError"]
