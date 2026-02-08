"""
REST endpoints for user-managed A2A agents.
"""

from __future__ import annotations

import ipaddress
from typing import Any, AsyncIterator
from urllib.parse import urlparse
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
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.service import ResolvedAgent
from app.integrations.a2a_client.validators import (
    validate_agent_card as validate_agent_card_payload,
)
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
from app.services.a2a_agents import (
    A2AAgentNotFoundError,
    A2AAgentRecord,
    A2AAgentValidationError,
    a2a_agent_service,
)
from app.services.a2a_runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.services.ws_ticket_service import ws_ticket_service
from app.utils.json_encoder import json_dumps

router = StrictAPIRouter(prefix="/me/a2a/agents", tags=["a2a"])
logger = get_logger(__name__)


def _serialize_stream_event(event: ClientEvent | Message) -> dict[str, Any]:
    if isinstance(event, tuple):
        resolved = event[1] if event[1] else event[0]
    else:
        resolved = event

    payload = resolved.model_dump(exclude_none=True)
    payload["validation_errors"] = validate_message(payload)
    return payload


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


def _ensure_a2a_enabled() -> None:
    if not settings.a2a_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A2A integration is disabled",
        )


def _normalize_host(value: str) -> str:
    return (value or "").strip().lower().rstrip(".")


def _parse_allowed_host_entry(value: str) -> tuple[str, int | None]:
    trimmed = (value or "").strip()
    if not trimmed:
        return "", None
    if "://" in trimmed:
        parsed = urlparse(trimmed)
        return parsed.hostname or "", parsed.port
    if trimmed.startswith("[") and "]" in trimmed:
        host_part, _, remainder = trimmed[1:].partition("]")
        if remainder.startswith(":") and remainder[1:].isdigit():
            return host_part, int(remainder[1:])
        return host_part, None
    if ":" in trimmed:
        host_part, port_part = trimmed.rsplit(":", 1)
        if port_part.isdigit():
            return host_part, int(port_part)
    return trimmed, None


def _match_allowed_host(host: str, allowed_host: str) -> bool:
    if not allowed_host:
        return False
    if allowed_host.startswith("*."):
        suffix = allowed_host[2:]
        if not suffix:
            return False
        return host == suffix or host.endswith(f".{suffix}")
    if allowed_host.startswith("."):
        suffix = allowed_host[1:]
        if not suffix:
            return False
        return host == suffix or host.endswith(f".{suffix}")
    return host == allowed_host


def _validate_proxy_target(parsed: Any) -> None:
    host = _normalize_host(parsed.hostname or "")
    if not host:
        raise HTTPException(status_code=400, detail="Card URL must be http(s)")
    if host == "localhost" or host.endswith(".localhost"):
        raise HTTPException(status_code=403, detail="Card URL host is not allowed")
    try:
        ip_value = ipaddress.ip_address(host)
    except ValueError:
        ip_value = None
    if ip_value and (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_multicast
        or ip_value.is_reserved
        or ip_value.is_unspecified
    ):
        raise HTTPException(status_code=403, detail="Card URL host is not allowed")

    allowed_hosts = [
        _parse_allowed_host_entry(entry)
        for entry in settings.a2a_proxy_allowed_hosts
        if (entry or "").strip()
    ]
    if not allowed_hosts:
        raise HTTPException(status_code=403, detail="Card URL host is not allowed")

    port = parsed.port
    if port is None:
        if parsed.scheme == "https":
            port = 443
        elif parsed.scheme == "http":
            port = 80
    for entry_host, entry_port in allowed_hosts:
        normalized_entry_host = _normalize_host(entry_host)
        if not normalized_entry_host:
            continue
        if entry_port is not None and port is not None and entry_port != port:
            continue
        if entry_port is not None and port is None:
            continue
        if _match_allowed_host(host, normalized_entry_host):
            return
    raise HTTPException(status_code=403, detail="Card URL host is not allowed")


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
    logger.info(
        "A2A agent create requested",
        extra={
            "user_id": str(current_user.id),
            "agent_name": payload.name,
            "card_url": payload.card_url,
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
            card_url=payload.card_url,
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
    logger.info(
        "A2A agent update requested",
        extra={
            "user_id": str(current_user.id),
            "agent_id": str(agent_id),
            "agent_name": payload.name,
            "card_url": payload.card_url,
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
            card_url=payload.card_url,
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
    status_code=status.HTTP_200_OK,
)
async def validate_agent_card(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    _ensure_a2a_enabled()
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
            "agent_url": runtime.resolved.url,
        },
    )
    try:
        card = await get_a2a_service().gateway.fetch_agent_card_detail(
            resolved=runtime.resolved, raise_on_failure=True
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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


@router.post(
    "/card:proxy",
    response_model=A2AAgentCardValidationResponse,
    status_code=status.HTTP_200_OK,
)
async def proxy_agent_card(
    payload: A2AAgentCardProxyRequest,
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    _ensure_a2a_enabled()

    card_url = _normalize_card_url(payload.card_url)
    headers = _build_proxy_headers(payload)
    logger.info(
        "A2A agent card proxy requested",
        extra={
            "user_id": str(current_user.id),
            "card_url": card_url,
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
        card = await get_a2a_service().gateway.fetch_agent_card_detail(
            resolved=resolved, raise_on_failure=True
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

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

    _ensure_a2a_enabled()
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
        agent_id=agent_id,
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
    current_user: User = Depends(get_ws_ticket_user),
):
    """
    WebSocket endpoint for A2A agent invocation with streaming responses.

    This endpoint accepts a WebSocket connection, waits for an invocation request,
    and then streams back events from the agent.
    """
    _ensure_a2a_enabled()
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
                "agent_url": runtime.resolved.url,
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
    except Exception as e:
        logger.error(f"WS error: {e}", exc_info=True)
        try:
            # Try to send error if still connected
            await websocket.send_text(
                json_dumps(
                    {"event": "error", "data": {"message": str(e)}}, ensure_ascii=False
                )
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
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    stream: bool = Query(False, description="Set to true for SSE streaming responses."),
):
    _ensure_a2a_enabled()
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
            "agent_url": runtime.resolved.url,
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
                    yield (f"data: {json_dumps(serialized, ensure_ascii=False)}\n\n")
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
