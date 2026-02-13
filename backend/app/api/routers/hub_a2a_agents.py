"""User-facing APIs for the global hub A2A agent catalog."""

from __future__ import annotations

from uuid import UUID

from fastapi import (
    Depends,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_ws_ticket_user_hub
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.transaction import commit_safely
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
from app.services.a2a_invoke_service import a2a_invoke_service
from app.services.hub_a2a_agents import HubA2AAgentNotFoundError, hub_a2a_agent_service
from app.services.hub_a2a_runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    hub_a2a_runtime_builder,
)
from app.services.session_hub import session_hub_service
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.logging_redaction import redact_url_for_logging

router = StrictAPIRouter(prefix="/a2a/agents", tags=["a2a-catalog"])
logger = get_logger(__name__)


def _status_code_for_invoke_session_error(detail: str) -> int:
    if detail == "session_not_found":
        return 404
    return 400


def _ws_error_code_for_invoke_session_error(detail: str) -> str:
    if detail == "session_not_found":
        return "session_not_found"
    return "invalid_session_id"


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
            "query_meta": summarize_query(payload.query),
        },
    )
    (
        local_session,
        local_source,
    ) = (None, None)
    try:
        (
            local_session,
            local_source,
        ) = await session_hub_service.ensure_local_session_for_invoke(
            db,
            user_id=current_user.id,
            agent_id=agent_id,
            agent_source="shared",
            session_key=payload.session_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=_status_code_for_invoke_session_error(str(exc)),
            detail=str(exc),
        ) from exc

    if stream:

        async def _on_complete(stream_text: str) -> None:
            if local_session is None or local_source is None:
                return
            await session_hub_service.record_local_invoke_messages(
                db,
                session=local_session,
                source=local_source,
                user_id=current_user.id,
                agent_id=agent_id,
                agent_source="shared",
                query=payload.query,
                response_content=stream_text or "",
                success=True,
                context_id=payload.context_id,
                invoke_metadata=payload.metadata,
                extra_metadata={"transport": "http_sse", "stream": True},
            )
            await commit_safely(db)

        async def _on_error(error_message: str) -> None:
            if local_session is None or local_source is None:
                return
            await session_hub_service.record_local_invoke_messages(
                db,
                session=local_session,
                source=local_source,
                user_id=current_user.id,
                agent_id=agent_id,
                agent_source="shared",
                query=payload.query,
                response_content=error_message,
                success=False,
                context_id=payload.context_id,
                invoke_metadata=payload.metadata,
                extra_metadata={"transport": "http_sse", "stream": True},
            )
            await commit_safely(db)

        return a2a_invoke_service.stream_sse(
            gateway=get_a2a_service().gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
            },
            on_complete=_on_complete,
            on_error=_on_error,
        )

    result = await get_a2a_service().gateway.invoke(
        resolved=runtime.resolved,
        query=payload.query,
        context_id=payload.context_id,
        metadata=payload.metadata,
    )
    if local_session is not None and local_source is not None:
        success = bool(result.get("success"))
        response_content = (
            result.get("content")
            if success
            else (result.get("error") or "A2A invocation failed")
        ) or ""
        await session_hub_service.record_local_invoke_messages(
            db,
            session=local_session,
            source=local_source,
            user_id=current_user.id,
            agent_id=agent_id,
            agent_source="shared",
            query=payload.query,
            response_content=response_content,
            success=success,
            context_id=payload.context_id,
            invoke_metadata=payload.metadata,
            extra_metadata={
                "transport": "http_json",
                "stream": False,
                "error_code": result.get("error_code"),
            },
        )
        await commit_safely(db)

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
        scope_type="hub_a2a_agent",
        scope_id=agent_id,
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
    current_user: User = Depends(get_ws_ticket_user_hub),
):
    """WebSocket endpoint for hub agent invocation with streaming responses."""
    await websocket.accept()

    try:
        data = await websocket.receive_json()
        try:
            payload = A2AAgentInvokeRequest.model_validate(data)
        except ValidationError:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Invalid request payload",
                error_code="invalid_request",
            )
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        if not payload.query.strip():
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Query must be a non-empty string",
                error_code="invalid_query",
            )
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        try:
            runtime = await hub_a2a_runtime_builder.build(
                db, user_id=current_user.id, agent_id=agent_id
            )
        except HubA2ARuntimeNotFoundError:
            # Keep non-enumerable semantics: close without disclosing whether the
            # agent exists or is simply not visible.
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Agent is unavailable",
                error_code="agent_unavailable",
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        except HubA2ARuntimeValidationError as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code="runtime_invalid",
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        logger.info(
            "Hub A2A agent invoke WS requested",
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "query_meta": summarize_query(payload.query),
            },
        )

        (
            local_session,
            local_source,
        ) = (None, None)
        try:
            (
                local_session,
                local_source,
            ) = await session_hub_service.ensure_local_session_for_invoke(
                db,
                user_id=current_user.id,
                agent_id=agent_id,
                agent_source="shared",
                session_key=payload.session_id,
            )
        except ValueError as exc:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message=str(exc),
                error_code=_ws_error_code_for_invoke_session_error(str(exc)),
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        async def _on_complete(stream_text: str) -> None:
            if local_session is None or local_source is None:
                return
            await session_hub_service.record_local_invoke_messages(
                db,
                session=local_session,
                source=local_source,
                user_id=current_user.id,
                agent_id=agent_id,
                agent_source="shared",
                query=payload.query,
                response_content=stream_text or "",
                success=True,
                context_id=payload.context_id,
                invoke_metadata=payload.metadata,
                extra_metadata={"transport": "ws", "stream": True},
            )
            await commit_safely(db)

        async def _on_error(error_message: str) -> None:
            if local_session is None or local_source is None:
                return
            await session_hub_service.record_local_invoke_messages(
                db,
                session=local_session,
                source=local_source,
                user_id=current_user.id,
                agent_id=agent_id,
                agent_source="shared",
                query=payload.query,
                response_content=error_message,
                success=False,
                context_id=payload.context_id,
                invoke_metadata=payload.metadata,
                extra_metadata={"transport": "ws", "stream": True},
            )
            await commit_safely(db)

        await a2a_invoke_service.stream_ws(
            websocket=websocket,
            gateway=get_a2a_service().gateway,
            resolved=runtime.resolved,
            query=payload.query,
            context_id=payload.context_id,
            metadata=payload.metadata,
            validate_message=validate_message,
            logger=logger,
            log_extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
            },
            on_complete=_on_complete,
            on_error=_on_error,
        )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"user_id": str(current_user.id)})
    except Exception:
        logger.error("Hub WS error", exc_info=True)
        try:
            await a2a_invoke_service.send_ws_error(
                websocket,
                message="Upstream streaming failed",
                error_code="upstream_stream_error",
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


__all__ = ["router"]
