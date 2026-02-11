"""
REST endpoints for user-managed A2A agents.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user, get_ws_ticket_user_me
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.service import ResolvedAgent
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_agent import (
    A2AAgentCreate,
    A2AAgentListResponse,
    A2AAgentResponse,
    A2AAgentUpdate,
)
from app.schemas.a2a_agent_card import (
    A2AAgentCardProxyRequest,
    A2AAgentCardValidationResponse,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.ws_ticket import WsTicketResponse
from app.services.a2a_agent_card_validation import fetch_and_validate_agent_card
from app.services.a2a_agents import (
    A2AAgentNotFoundError,
    A2AAgentRecord,
    A2AAgentValidationError,
    a2a_agent_service,
)
from app.services.a2a_invoke_service import a2a_invoke_service
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.logging_redaction import redact_url_for_logging
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

router = StrictAPIRouter(prefix="/me/a2a/agents", tags=["a2a"])
logger = get_logger(__name__)


def _build_response(record: A2AAgentRecord) -> A2AAgentResponse:
    agent = record.agent
    payload = {
        "id": agent.id,
        "name": agent.name,
        "card_url": agent.card_url,
        "auth_type": agent.auth_type,
        "auth_header": agent.auth_header,
        "auth_scheme": agent.auth_scheme,
        "enabled": agent.enabled,
        "tags": agent.tags or [],
        "extra_headers": agent.extra_headers or {},
        "token_last4": record.token_last4,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }
    return A2AAgentResponse.model_validate(payload)


def _validate_proxy_target(parsed: Any) -> None:
    try:
        validate_outbound_http_url(
            parsed.geturl(),
            allowed_hosts=settings.a2a_proxy_allowed_hosts,
            purpose="Card URL",
        )
    except OutboundURLNotAllowedError as exc:
        if exc.code in {"missing_url", "invalid_scheme", "missing_host"}:
            raise HTTPException(
                status_code=400, detail="Card URL must be http(s)"
            ) from exc
        raise HTTPException(
            status_code=403, detail="Card URL host is not allowed"
        ) from exc


def _normalize_card_url(value: str) -> str:
    trimmed = (value or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Card URL is required")
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Card URL must be http(s)")
    _validate_proxy_target(parsed)
    return trimmed


def _build_proxy_headers(payload: A2AAgentCardProxyRequest) -> dict[str, str]:
    headers = dict(payload.extra_headers or {})
    if payload.auth_type == "bearer":
        token = (payload.token or "").strip()
        if not token:
            raise HTTPException(status_code=400, detail="Bearer token is required")
        header_name = (
            payload.auth_header or "Authorization"
        ).strip() or "Authorization"
        scheme = (payload.auth_scheme or "Bearer").strip()
        headers[header_name] = f"{scheme} {token}" if scheme else token
    elif payload.auth_type != "none":
        raise HTTPException(status_code=400, detail="Unsupported auth_type")
    return headers


@router.get("", response_model=A2AAgentListResponse)
async def list_agents(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
) -> A2AAgentListResponse:
    logger.info(
        "A2A agents list requested",
        extra={
            "user_id": str(current_user.id),
            "page": page,
            "size": size,
        },
    )
    items = await a2a_agent_service.list_agents(db, user_id=current_user.id)
    total = len(items)
    pages = (total + size - 1) // size if size else 0
    offset = (page - 1) * size
    page_items = items[offset : offset + size]
    return A2AAgentListResponse(
        items=[_build_response(item) for item in page_items],
        pagination={
            "page": page,
            "size": size,
            "total": total,
            "pages": pages,
        },
        meta={},
    )


@router.post("", response_model=A2AAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    *,
    payload: A2AAgentCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    normalized_card_url = _normalize_card_url(payload.card_url)
    logger.info(
        "A2A agent create requested",
        extra={
            "user_id": str(current_user.id),
            "agent_name": payload.name,
            "card_url": redact_url_for_logging(normalized_card_url),
            "auth_type": payload.auth_type,
            "enabled": payload.enabled,
            "tags_count": len(payload.tags or []),
            "extra_header_keys": sorted((payload.extra_headers or {}).keys()),
        },
    )
    try:
        record = await a2a_agent_service.create_agent(
            db,
            user_id=current_user.id,
            name=payload.name,
            card_url=normalized_card_url,
            auth_type=payload.auth_type,
            auth_header=payload.auth_header,
            auth_scheme=payload.auth_scheme,
            enabled=payload.enabled,
            tags=payload.tags,
            extra_headers=payload.extra_headers,
            token=payload.token,
        )
        return _build_response(record)
    except A2AAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=A2AAgentResponse)
async def update_agent(
    *,
    agent_id: UUID,
    payload: A2AAgentUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    normalized_card_url = (
        _normalize_card_url(payload.card_url) if payload.card_url is not None else None
    )
    logger.info(
        "A2A agent update requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_name": payload.name,
            "card_url": redact_url_for_logging(normalized_card_url),
            "auth_type": payload.auth_type,
            "enabled": payload.enabled,
            "tags_count": len(payload.tags) if payload.tags is not None else None,
            "extra_header_keys": (
                sorted(payload.extra_headers.keys())
                if payload.extra_headers is not None
                else None
            ),
        },
    )
    try:
        record = await a2a_agent_service.update_agent(
            db,
            user_id=current_user.id,
            agent_id=agent_id,
            name=payload.name,
            card_url=normalized_card_url,
            auth_type=payload.auth_type,
            auth_header=payload.auth_header,
            auth_scheme=payload.auth_scheme,
            enabled=payload.enabled,
            tags=payload.tags,
            extra_headers=payload.extra_headers,
            token=payload.token,
        )
        return _build_response(record)
    except A2AAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except A2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_agent(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    logger.info(
        "A2A agent delete requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
        },
    )
    try:
        await a2a_agent_service.delete_agent(
            db,
            user_id=current_user.id,
            agent_id=agent_id,
        )
    except A2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/card:validate",
    response_model=A2AAgentCardValidationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def validate_agent_card(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "A2A agent card validation requested",
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
    "/card:proxy",
    response_model=A2AAgentCardValidationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def proxy_agent_card(
    payload: A2AAgentCardProxyRequest,
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    card_url = _normalize_card_url(payload.card_url)
    headers = _build_proxy_headers(payload)
    logger.info(
        "A2A agent card proxy requested",
        extra={
            "user_id": str(current_user.id),
            "card_url": redact_url_for_logging(card_url),
            "auth_type": payload.auth_type,
            "extra_header_keys": sorted((payload.extra_headers or {}).keys()),
        },
    )
    resolved = ResolvedAgent(
        name=card_url,
        url=card_url,
        description=None,
        metadata={},
        headers=headers,
    )

    try:
        return await fetch_and_validate_agent_card(
            gateway=get_a2a_service().gateway,
            resolved=resolved,
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/{agent_id}/invoke/ws-token",
    response_model=WsTicketResponse,
    status_code=status.HTTP_200_OK,
)
async def issue_invoke_ws_token(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> WsTicketResponse:
    """Issue a one-time WS ticket for agent invocation."""
    try:
        await a2a_agent_service.get_agent(
            db,
            user_id=current_user.id,
            agent_id=agent_id,
        )
    except A2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    issued = await ws_ticket_service.issue_ticket(
        db,
        user_id=current_user.id,
        scope_type="me_a2a_agent",
        scope_id=agent_id,
    )
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )


@router.websocket("/{agent_id}/invoke/ws")
async def invoke_agent_ws(
    *,
    websocket: WebSocket,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_ws_ticket_user_me),
):
    """
    WebSocket endpoint for A2A agent invocation with streaming responses.

    This endpoint accepts a WebSocket connection, waits for an invocation request,
    and then streams back events from the agent.
    """
    await websocket.accept()

    try:
        # Receive the request payload
        data = await websocket.receive_json()
        payload = A2AAgentInvokeRequest.model_validate(data)

        if not payload.query.strip():
            await websocket.send_json({"error": "Query must be a non-empty string"})
            await websocket.close(code=status.WS_1003_UNSUPPORTED_DATA)
            return

        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )

        logger.info(
            "A2A agent invoke WS requested",
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "query_meta": summarize_query(payload.query),
            },
        )

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
        )

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"user_id": str(current_user.id)})
    except Exception:
        logger.error("WS error", exc_info=True)
        try:
            # Try to send error if still connected
            await websocket.send_text(
                '{"event":"error","data":{"message":"Upstream streaming failed"}}'
            )
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.post(
    "/{agent_id}/invoke",
    response_model=A2AAgentInvokeResponse,
    status_code=status.HTTP_200_OK,
)
async def invoke_agent(
    *,
    agent_id: UUID,
    payload: A2AAgentInvokeRequest,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    stream: bool = Query(False, description="Set to true for SSE streaming responses."),
):
    response.headers["Cache-Control"] = "no-store"
    if not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query must be a non-empty string")

    try:
        runtime = await a2a_runtime_builder.build(
            db, user_id=current_user.id, agent_id=agent_id
        )
    except A2ARuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except A2ARuntimeValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "A2A agent invoke requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
            "stream": stream,
            "query_meta": summarize_query(payload.query),
        },
    )
    if stream:
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
