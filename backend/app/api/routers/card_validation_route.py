"""Shared helper for A2A agent card validation endpoints."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import HTTPException

from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.schemas.a2a_agent_card import A2AAgentCardValidationResponse
from app.services.a2a_agent_card_validation import fetch_and_validate_agent_card
from app.utils.logging_redaction import redact_url_for_logging


async def run_card_validation_route(
    *,
    build_runtime: Callable[[], Awaitable[Any]],
    runtime_not_found_errors: tuple[type[Exception], ...],
    runtime_not_found_status_code: int,
    runtime_validation_errors: tuple[type[Exception], ...],
    runtime_validation_status_code: int,
    gateway: Any,
    logger: Any,
    log_message: str,
    log_extra: dict[str, Any],
) -> A2AAgentCardValidationResponse:
    try:
        runtime = await build_runtime()
    except runtime_not_found_errors as exc:
        raise HTTPException(
            status_code=runtime_not_found_status_code, detail=str(exc)
        ) from exc
    except runtime_validation_errors as exc:
        raise HTTPException(
            status_code=runtime_validation_status_code, detail=str(exc)
        ) from exc

    logger.info(
        log_message,
        extra={
            **log_extra,
            "agent_url": redact_url_for_logging(runtime.resolved.url),
        },
    )

    try:
        return await fetch_and_validate_agent_card(
            gateway=gateway,
            resolved=runtime.resolved,
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


__all__ = ["run_card_validation_route"]
