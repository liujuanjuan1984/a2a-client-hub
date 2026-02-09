"""User-facing APIs for the global hub A2A agent catalog."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_client import get_a2a_service
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.hub_a2a_agent import HubA2AAgentUserListResponse, HubA2AAgentUserResponse
from app.services.hub_a2a_agents import hub_a2a_agent_service
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)

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
    total = len(items)
    pages = (total + size - 1) // size if size else 0
    offset = (page - 1) * size
    page_items = items[offset : offset + size]
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
        pagination={"page": page, "size": size, "total": total, "pages": pages},
        meta={},
    )


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
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must be a non-empty string")

    if stream:
        raise HTTPException(
            status_code=400,
            detail="Streaming is not supported for hub agents yet",
        )

    try:
        runtime = await hub_a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except HubA2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2ARuntimeValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "Hub A2A agent invoke requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": runtime.resolved.url,
            "query_preview": payload.query[:50],
        },
    )

    result = await get_a2a_service().gateway.invoke(
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    return A2AAgentInvokeResponse(
        success=bool(result.get("success")),
        content=result.get("content"),
        error=result.get("error"),
        error_code=result.get("error_code"),
        agent_name=runtime.resolved.name,
        agent_url=runtime.resolved.url,
    )


__all__ = ["router"]
