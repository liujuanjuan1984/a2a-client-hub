"""User-facing APIs for the global hub A2A agent catalog."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_ws_ticket_user_hub
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_agent_card import A2AAgentCardValidationResponse
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.hub_a2a_agent import (
    HubA2AAgentUserListResponse,
    HubA2AAgentUserResponse,
)
from app.schemas.ws_ticket import WsTicketResponse
from app.services.a2a_agent_card_validation import fetch_and_validate_agent_card
from app.services.hub_a2a_agents import HubA2AAgentNotFoundError, hub_a2a_agent_service
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)
from app.services.invoke_route_runner import (
    run_http_invoke_route,
    run_issue_ws_ticket_route,
    run_ws_invoke_route,
)
from app.utils.logging_redaction import redact_url_for_logging
from app.utils.pagination import paginate

router = StrictAPIRouter(prefix="/a2a/agents", tags=["a2a-catalog"])
logger = get_logger(__name__)


@router.get("", response_model=HubA2AAgentUserListResponse)
async def list_hub_agents_for_user(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
) -> HubA2AAgentUserListResponse:
    items = await hub_a2a_agent_service.list_visible_agents_for_user(
        db, user_id=current_user.id
    )
    page_items, pagination = paginate(items, page=page, size=size)
    return HubA2AAgentUserListResponse(
        items=[
            HubA2AAgentUserResponse(
                id=item.id,
                name=item.name,
                card_url=item.card_url,
                tags=item.tags or [],
            )
            for item in page_items
        ],
        pagination=pagination,
        meta={},
    )


@router.post(
    "/{agent_id}/card:validate",
    response_model=A2AAgentCardValidationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def validate_hub_agent_card(
    *,
    agent_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    response.headers["Cache-Control"] = "no-store"

    try:
        runtime = await hub_a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except HubA2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2ARuntimeValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "Hub A2A agent card validation requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
        },
    )
    try:
        return await fetch_and_validate_agent_card(
            gateway=get_a2a_service().gateway,
            resolved=runtime.resolved,
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/{agent_id}/invoke",
    response_model=A2AAgentInvokeResponse,
    status_code=status.HTTP_200_OK,
)
async def invoke_hub_agent(
    *,
    agent_id: UUID,
    payload: A2AAgentInvokeRequest,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    stream: bool = Query(False, description="Set to true for SSE streaming responses."),
) -> A2AAgentInvokeResponse:
    response.headers["Cache-Control"] = "no-store"
    return await run_http_invoke_route(
        db=db,
        user_id=current_user.id,
        agent_id=agent_id,
        agent_source="shared",
        payload=payload,
        stream=stream,
        gateway=get_a2a_service().gateway,
        runtime_builder=lambda: hub_a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        ),
        runtime_not_found_errors=(HubA2ARuntimeNotFoundError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(HubA2ARuntimeValidationError,),
        runtime_validation_status_code=502,
        validate_message=validate_message,
        logger=logger,
        invoke_log_message="Hub A2A agent invoke requested",
        invoke_log_extra_builder=lambda request, runtime: {
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
            "stream": stream,
            "query_meta": summarize_query(request.query),
        },
    )


@router.post(
    "/{agent_id}/invoke/ws-token",
    response_model=WsTicketResponse,
    status_code=status.HTTP_200_OK,
)
async def issue_hub_invoke_ws_token(
    *,
    agent_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> WsTicketResponse:
    response.headers["Cache-Control"] = "no-store"
    return await run_issue_ws_ticket_route(
        db=db,
        user_id=current_user.id,
        scope_type="hub_a2a_agent",
        scope_id=agent_id,
        ensure_access=lambda: hub_a2a_agent_service.ensure_visible_for_user(
            db, user_id=current_user.id, agent_id=agent_id
        ),
        not_found_errors=(HubA2AAgentNotFoundError,),
        not_found_status_code=404,
        # Keep the hub catalog non-enumerable: not found is always 404.
        not_found_detail=lambda exc: str(exc),
    )


@router.websocket("/{agent_id}/invoke/ws")
async def invoke_hub_agent_ws(
    *,
    websocket: WebSocket,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_ws_ticket_user_hub),
):
    """WebSocket endpoint for hub agent invocation with streaming responses."""
    await run_ws_invoke_route(
        websocket=websocket,
        db=db,
        user_id=current_user.id,
        agent_id=agent_id,
        agent_source="shared",
        gateway=get_a2a_service().gateway,
        runtime_builder=lambda: hub_a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        ),
        runtime_not_found_errors=(HubA2ARuntimeNotFoundError,),
        runtime_not_found_message="Agent is unavailable",
        runtime_not_found_code="agent_unavailable",
        runtime_validation_errors=(HubA2ARuntimeValidationError,),
        validate_message=validate_message,
        logger=logger,
        invoke_log_message="Hub A2A agent invoke WS requested",
        invoke_log_extra_builder=lambda payload, runtime: {
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
            "query_meta": summarize_query(payload.query),
        },
        unexpected_log_message="Hub WS error",
    )


__all__ = ["router"]
