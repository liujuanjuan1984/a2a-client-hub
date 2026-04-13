"""Shared structured reason codes for agent health check results."""

from __future__ import annotations


class AgentHealthReasonCode:
    """Canonical persisted reason codes for agent health checks."""

    CARD_VALIDATION_FAILED = "card_validation_failed"
    RUNTIME_VALIDATION_FAILED = "runtime_validation_failed"
    AGENT_UNAVAILABLE = "agent_unavailable"
    CLIENT_RESET_REQUIRED = "client_reset_required"
    CREDENTIAL_REQUIRED = "credential_required"
    UNEXPECTED_ERROR = "unexpected_error"
