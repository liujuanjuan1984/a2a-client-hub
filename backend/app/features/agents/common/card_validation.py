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
from app.integrations.a2a_client.protobuf import (
    parse_agent_card,
    to_protojson_object,
)
from app.integrations.a2a_client.validators import (
    validate_agent_card as validate_agent_card_payload,
)
from app.integrations.a2a_extensions.compatibility_profile_diagnostics import (
    diagnose_compatibility_profile,
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

    raw_card_payload = to_protojson_object(card)
    if raw_card_payload is None:
        return A2AAgentCardValidationResponse(
            success=False,
            message="Agent card payload must be a JSON object",
        )
    validation_errors: list[str] = []
    validation_warnings: list[str] = []
    extension_warnings: list[str] = []
    diagnostics_card: AgentCard | None = card if isinstance(card, AgentCard) else None
    strict_parse_error: str | None = None

    try:
        if diagnostics_card is None:
            diagnostics_card = parse_agent_card(
                raw_card_payload,
                ignore_unknown_fields=False,
            )
    except Exception as exc:
        strict_parse_error = (
            "Agent card payload is not compatible with A2A 1.0 canonical parsing: "
            f"{exc}"
        )
        try:
            diagnostics_card = parse_agent_card(raw_card_payload)
        except Exception:
            diagnostics_card = None

    card_payload = (
        to_protojson_object(diagnostics_card)
        if diagnostics_card is not None
        else raw_card_payload
    )
    if card_payload is None:
        card_payload = raw_card_payload

    validation_result = validate_agent_card_payload(card_payload)
    validation_errors.extend(validation_result.errors)
    validation_warnings.extend(validation_result.warnings)
    if strict_parse_error is not None:
        validation_errors.insert(0, strict_parse_error)

    session_query = (
        diagnose_session_query(diagnostics_card)
        if diagnostics_card is not None
        else None
    )
    compatibility_profile = (
        diagnose_compatibility_profile(diagnostics_card)
        if diagnostics_card is not None
        else None
    )
    if session_query and session_query.status == "invalid" and session_query.error:
        extension_warnings.append(
            f"Shared session query contract is invalid: {session_query.error}"
        )
    elif (
        session_query
        and session_query.status == "unsupported"
        and session_query.declared
    ):
        extension_warnings.append(
            session_query.error
            or "Shared session query extension is not supported by Hub"
        )
    if (
        compatibility_profile
        and compatibility_profile.status == "invalid"
        and compatibility_profile.error
    ):
        extension_warnings.append(
            "Compatibility profile contract is invalid: "
            f"{compatibility_profile.error}"
        )
    validation_warnings.extend(extension_warnings)

    success = not validation_errors
    if success and validation_warnings:
        message = "Agent card validated with warnings"
    elif success:
        message = "Agent card validated"
    else:
        message = "Agent card validation issues detected"

    response_kwargs: dict[str, Any] = {
        "success": success,
        "message": message,
        "card_name": card_payload.get("name"),
        "card_description": card_payload.get("description"),
        "card": card_payload,
        "shared_session_query": session_query,
        "compatibility_profile": compatibility_profile,
    }
    if validation_warnings:
        response_kwargs["validation_warnings"] = validation_warnings
    if app.core.config.settings.debug:
        response_kwargs["validation_errors"] = validation_errors

    return A2AAgentCardValidationResponse(**response_kwargs)
