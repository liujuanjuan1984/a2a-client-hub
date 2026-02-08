"""Errors for A2A extension discovery and invocation."""

from __future__ import annotations


class A2AExtensionError(RuntimeError):
    """Base error for A2A extension handling."""


class A2AExtensionNotSupportedError(A2AExtensionError):
    """Raised when the downstream agent does not support the required extension."""


class A2AExtensionContractError(A2AExtensionError):
    """Raised when an extension exists but its declared contract is invalid/incomplete."""


class A2AExtensionUpstreamError(A2AExtensionError):
    """Raised when an upstream JSON-RPC call failed."""

    def __init__(
        self,
        *,
        message: str,
        error_code: str,
        upstream_error: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.upstream_error = upstream_error or None


__all__ = [
    "A2AExtensionError",
    "A2AExtensionNotSupportedError",
    "A2AExtensionContractError",
    "A2AExtensionUpstreamError",
]

