"""Agent card fetch and validation helpers.

This logic is shared by both user-managed (/me) and hub catalog (/a2a) routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from a2a.types import AgentCard

import app.core.config
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.invoke_session import AgentResolutionPolicy
from app.integrations.a2a_client.validators import (
    validate_agent_card as validate_agent_card_payload,
)
from app.integrations.a2a_extensions.session_query_diagnostics import (
    diagnose_session_query,
)
from app.schemas.a2a_agent_card import A2AAgentCardValidationResponse

if TYPE_CHECKING:
    from app.integrations.a2a_client.gateway import A2AGateway
    from app.integrations.a2a_client.types import ResolvedAgent


async def fetch_and_validate_agent_card(
    *,
    gateway: A2AGateway,
    resolved: ResolvedAgent,
) -> A2AAgentCardValidationResponse:
    """Fetch the agent card and validate it.

    Raises:
        A2AAgentUnavailableError, A2AClientResetRequiredError: when the upstream
            is unreachable or requires a reset. Callers should map these to 502.
    """

    try:
        card = await gateway.fetch_agent_card_detail(
            resolved=resolved,
            raise_on_failure=True,
            policy=AgentResolutionPolicy.FRESH_PROBE,
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError):
        raise

    if not card:
        return A2AAgentCardValidationResponse(
            success=False,
            message="Agent card unavailable",
        )

    card_payload = card.model_dump(exclude_none=True)
    validation_result = validate_agent_card_payload(card_payload)
    validation_errors = list(validation_result.errors)
    validation_warnings = list(validation_result.warnings)
    diagnostics_card: AgentCard | None = None
    try:
        diagnostics_card = AgentCard.model_validate(card_payload)
    except Exception:  # noqa: BLE001
        diagnostics_card = None

    session_query = (
        diagnose_session_query(diagnostics_card)
        if diagnostics_card is not None
        else None
    )
    if session_query and session_query.status == "invalid" and session_query.error:
        validation_errors.append(session_query.error)

    success = not validation_errors
    if success and validation_warnings:
        message = "Agent card validated with warnings"
    elif success:
        message = "Agent card validated"
    elif session_query and session_query.status == "invalid" and session_query.error:
        message = f"Shared session query contract is invalid: {session_query.error}"
    else:
        message = "Agent card validation issues detected"

    response_kwargs: dict[str, Any] = {
        "success": success,
        "message": message,
        "card_name": card_payload.get("name"),
        "card_description": card_payload.get("description"),
        "card": card_payload,
        "shared_session_query": session_query,
    }
    if validation_warnings:
        response_kwargs["validation_warnings"] = validation_warnings
    if app.core.config.settings.debug:
        response_kwargs["validation_errors"] = validation_errors

    return A2AAgentCardValidationResponse(**response_kwargs)


__all__ = ["fetch_and_validate_agent_card"]
