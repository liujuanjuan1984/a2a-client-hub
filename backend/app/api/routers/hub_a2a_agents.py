"""User-facing APIs for the global hub A2A agent catalog."""

from __future__ import annotations

from typing import Any, AsyncIterator
from uuid import UUID

from a2a.client.client import ClientEvent
from a2a.types import Message
from fastapi import (
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_ws_ticket_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.hub_a2a_agent import (
    HubA2AAgentUserListResponse,
    HubA2AAgentUserResponse,
)
from app.schemas.ws_ticket import WsTicketResponse
from app.services.hub_a2a_agents import HubA2AAgentNotFoundError, hub_a2a_agent_service
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.json_encoder import json_dumps
from app.utils.logging_redaction import redact_url_for_logging

router = StrictAPIRouter(prefix="/a2a/agents", tags=["a2a-catalog"])
logger = get_logger(__name__)


def _serialize_stream_event(event: ClientEvent | Message) -> dict[str, Any]:
    if isinstance(event, tuple):
        resolved = event[1] if event[1] else event[0]
    else:
        resolved = event

    payload = resolved.model_dump(exclude_none=True)
    payload["validation_errors"] = validate_message(payload)
    return payload


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
            "agent_url": redact_url_for_logging(runtime.resolved.url),
            "stream": stream,
            "query_preview": payload.query[:50],
        },
    )

    if stream:

        async def event_generator() -> AsyncIterator[str]:
            try:
                async for event in get_a2a_service().gateway.stream(
                    resolved=runtime.resolved,
                    query=payload.query,
                    context_id=payload.context_id,
                    metadata=payload.metadata,
                ):
                    serialized = _serialize_stream_event(event)
                    yield f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n"
            except Exception as stream_error:
                yield (
                    "event: error\n"
                    f"data: {json_dumps({'message': str(stream_error)}, ensure_ascii=False)}\n\n"
                )
            finally:
                yield "event: stream_end\ndata: {}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
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
    try:
        await hub_a2a_agent_service.ensure_visible_for_user(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except HubA2AAgentNotFoundError as exc:
        # Keep the hub catalog non-enumerable: not found is always 404.
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    issued = await ws_ticket_service.issue_ticket(
        db,
        user_id=current_user.id,
        agent_id=agent_id,
    )
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )


@router.websocket("/{agent_id}/invoke/ws")
async def invoke_hub_agent_ws(
    *,
    websocket: WebSocket,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_ws_ticket_user),
):
    """WebSocket endpoint for hub agent invocation with streaming responses."""
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        payload = A2AAgentInvokeRequest.model_validate(data)

        if not payload.query.strip():
            await websocket.send_json({"error": "Query must be a non-empty string"})
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        try:
            runtime = await hub_a2a_runtime_builder.build(
                db, user_id=current_user.id, agent_id=agent_id
            )
        except HubA2ARuntimeNotFoundError:
            # Keep non-enumerable semantics: close without disclosing whether the
            # agent exists or is simply not visible.
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except HubA2ARuntimeValidationError:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        logger.info(
            "Hub A2A agent invoke WS requested",
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "query_preview": payload.query[:50],
            },
        )

        try:
            async for event in get_a2a_service().gateway.stream(
                resolved=runtime.resolved,
                query=payload.query,
                context_id=payload.context_id,
                metadata=payload.metadata,
            ):
                serialized = _serialize_stream_event(event)
                await websocket.send_text(json_dumps(serialized, ensure_ascii=False))
        except Exception as stream_error:
            await websocket.send_text(
                json_dumps(
                    {"event": "error", "data": {"message": str(stream_error)}},
                    ensure_ascii=False,
                )
            )
        finally:
            await websocket.send_text(json_dumps({"event": "stream_end", "data": {}}))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"user_id": str(current_user.id)})
    except Exception as exc:
        logger.error("Hub WS error", exc_info=True)
        try:
            await websocket.send_text(
                json_dumps(
                    {"event": "error", "data": {"message": str(exc)}},
                    ensure_ascii=False,
                )
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


__all__ = ["router"]
