"""Agent card fetch and validation helpers.

This logic is shared by both user-managed (/me) and hub catalog (/a2a) routes.
"""

from __future__ import annotations

from typing import Any

from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.validators import (
    validate_agent_card as validate_agent_card_payload,
)
from app.schemas.a2a_agent_card import A2AAgentCardValidationResponse


async def fetch_and_validate_agent_card(
    *,
    gateway: Any,
    resolved: Any,
) -> A2AAgentCardValidationResponse:
    """Fetch the agent card and validate it.

    Raises:
        A2AAgentUnavailableError, A2AClientResetRequiredError: when the upstream
            is unreachable or requires a reset. Callers should map these to 502.
    """

    try:
        card = await gateway.fetch_agent_card_detail(
            resolved=resolved, raise_on_failure=True
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError):
        raise

    if not card:
        return A2AAgentCardValidationResponse(
            success=False,
            message="Agent card unavailable",
        )

    card_payload = card.model_dump(exclude_none=True)
    validation_errors = validate_agent_card_payload(card_payload)
    success = not validation_errors
    message = (
        "Agent card validated" if success else "Agent card validation issues detected"
    )

    return A2AAgentCardValidationResponse(
        success=success,
        message=message,
        card_name=card_payload.get("name"),
        card_description=card_payload.get("description"),
        card=card_payload,
        validation_errors=validation_errors,
    )


__all__ = ["fetch_and_validate_agent_card"]
