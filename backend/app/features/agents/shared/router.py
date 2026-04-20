"""Shared A2A agent user-facing feature router."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, WebSocket, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_async_db,
    get_current_user,
    get_ws_ticket_user_hub,
)
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.transaction import load_for_external_call
from app.features.agents.common.card_validation import fetch_and_validate_agent_card
from app.features.agents.shared.runtime import (
    SharedAgentRuntimeNotFoundError,
    SharedAgentRuntimeValidationError,
    SharedAgentUserCredentialRequiredError,
    shared_agent_runtime_builder,
)
from app.features.agents.shared.schemas import (
    SharedAgentListMeta,
    SharedAgentPagination,
    SharedAgentUserCredentialStatusResponse,
    SharedAgentUserCredentialUpsertRequest,
    SharedAgentUserListResponse,
    SharedAgentUserResponse,
)
from app.features.agents.shared.service import (
    SharedAgentNotFoundError,
    SharedAgentValidationError,
    shared_agent_service,
)
from app.features.invoke.route_runner import (
    run_http_invoke_route,
    run_issue_ws_ticket_route,
    run_ws_invoke_route,
)
from app.integrations.a2a_client import get_a2a_service
from app.integrations.a2a_client.controls import summarize_query
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.validators import validate_message
from app.schemas.a2a_agent_card import A2AAgentCardValidationResponse
from app.schemas.a2a_invoke import A2AAgentInvokeRequest, A2AAgentInvokeResponse
from app.schemas.ws_ticket import WsTicketResponse
from app.utils.logging_redaction import redact_url_for_logging

router = StrictAPIRouter(prefix="/a2a/agents", tags=["a2a-catalog"])
logger = get_logger(__name__)


@router.get("", response_model=SharedAgentUserListResponse)
async def list_shared_agents_for_user(
    *,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
) -> SharedAgentUserListResponse:
    current_user_id = cast(UUID, current_user.id)
    items, total = await shared_agent_service.list_visible_agents_for_user(
        db,
        user_id=current_user_id,
        page=page,
        size=size,
    )
    pages = (total + size - 1) // size if size else 0
    return SharedAgentUserListResponse(
        items=[
            SharedAgentUserResponse(
                id=item.id,
                name=item.name,
                card_url=item.card_url,
                auth_type=cast(Any, item.auth_type),
                credential_mode=cast(Any, item.credential_mode),
                credential_configured=bool(item.credential_configured),
                credential_display_hint=item.credential_display_hint,
                tags=cast(list[str], item.tags or []),
            )
            for item in items
        ],
        pagination=SharedAgentPagination(
            page=page,
            size=size,
            total=total,
            pages=pages,
        ),
        meta=SharedAgentListMeta(),
    )


@router.get(
    "/{agent_id}/credential",
    response_model=SharedAgentUserCredentialStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_shared_agent_user_credential_status(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SharedAgentUserCredentialStatusResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        status_record = await shared_agent_service.get_user_credential_status(
            db,
            user_id=current_user_id,
            agent_id=agent_id,
        )
    except SharedAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SharedAgentUserCredentialStatusResponse(
        agent_id=status_record.agent_id,
        auth_type=cast(Any, status_record.auth_type),
        credential_mode=cast(Any, status_record.credential_mode),
        configured=status_record.configured,
        token_last4=status_record.token_last4,
        username_hint=status_record.username_hint,
    )


@router.put(
    "/{agent_id}/credential",
    response_model=SharedAgentUserCredentialStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def upsert_shared_agent_user_credential(
    *,
    agent_id: UUID,
    payload: SharedAgentUserCredentialUpsertRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SharedAgentUserCredentialStatusResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        status_record = await shared_agent_service.upsert_user_credential(
            db,
            user_id=current_user_id,
            agent_id=agent_id,
            token=payload.token,
            basic_username=payload.basic_username,
            basic_password=payload.basic_password,
        )
    except SharedAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SharedAgentUserCredentialStatusResponse(
        agent_id=status_record.agent_id,
        auth_type=cast(Any, status_record.auth_type),
        credential_mode=cast(Any, status_record.credential_mode),
        configured=status_record.configured,
        token_last4=status_record.token_last4,
        username_hint=status_record.username_hint,
    )


@router.delete(
    "/{agent_id}/credential",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_shared_agent_user_credential(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    current_user_id = cast(UUID, current_user.id)
    try:
        await shared_agent_service.delete_user_credential(
            db,
            user_id=current_user_id,
            agent_id=agent_id,
        )
    except SharedAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{agent_id}/card:validate",
    response_model=A2AAgentCardValidationResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
async def validate_shared_agent_card(
    *,
    agent_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> A2AAgentCardValidationResponse:
    current_user_id = cast(UUID, current_user.id)
    response.headers["Cache-Control"] = "no-store"

    try:
        runtime = await load_for_external_call(
            db,
            lambda session: shared_agent_runtime_builder.build(
                session,
                user_id=current_user_id,
                agent_id=agent_id,
            ),
        )
    except SharedAgentRuntimeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SharedAgentUserCredentialRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SharedAgentRuntimeValidationError as exc:
        logger.exception(
            "Shared A2A agent runtime validation failed during card validation",
            extra={
                "user_id": str(current_user_id),
                "agent_id": str(agent_id),
            },
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info(
        "Shared A2A agent card validation requested",
        extra={
            "user_id": str(current_user_id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
        },
    )
    try:
        return await fetch_and_validate_agent_card(
            gateway=cast(Any, get_a2a_service()).gateway,
            resolved=runtime.resolved,
        )
    except (A2AAgentUnavailableError, A2AClientResetRequiredError) as exc:
        logger.exception(
            "Shared A2A agent card validation failed",
            extra={
                "user_id": str(current_user_id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
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
) -> Any:
    response.headers["Cache-Control"] = "no-store"
    current_user_id = cast(UUID, current_user.id)
    return await run_http_invoke_route(
        db=db,
        user_id=current_user_id,
        agent_id=agent_id,
        agent_source="shared",
        payload=payload,
        stream=stream,
        gateway=cast(Any, get_a2a_service()).gateway,
        runtime_builder=lambda: shared_agent_runtime_builder.build(
            db, user_id=current_user_id, agent_id=agent_id
        ),
        runtime_not_found_errors=(SharedAgentRuntimeNotFoundError,),
        runtime_not_found_status_code=404,
        runtime_validation_errors=(
            SharedAgentUserCredentialRequiredError,
            SharedAgentRuntimeValidationError,
        ),
        runtime_validation_status_code=502,
        runtime_validation_status_overrides=(
            (SharedAgentUserCredentialRequiredError, 409),
        ),
        validate_message=validate_message,
        logger=logger,
        invoke_log_message="Shared A2A agent invoke requested",
        invoke_log_extra_builder=lambda request, runtime: {
            "user_id": str(current_user_id),
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
    current_user_id = cast(UUID, current_user.id)
    return await run_issue_ws_ticket_route(
        db=db,
        user_id=current_user_id,
        scope_type="hub_a2a_agent",
        scope_id=agent_id,
        ensure_access=lambda: shared_agent_service.ensure_visible_for_user(
            db, user_id=current_user_id, agent_id=agent_id
        ),
        not_found_errors=(SharedAgentNotFoundError,),
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
) -> None:
    """WebSocket endpoint for hub agent invocation with streaming responses."""
    current_user_id = cast(UUID, current_user.id)
    await run_ws_invoke_route(
        websocket=websocket,
        db=db,
        user_id=current_user_id,
        agent_id=agent_id,
        agent_source="shared",
        gateway=cast(Any, get_a2a_service()).gateway,
        runtime_builder=lambda: shared_agent_runtime_builder.build(
            db, user_id=current_user_id, agent_id=agent_id
        ),
        runtime_not_found_errors=(SharedAgentRuntimeNotFoundError,),
        runtime_not_found_message="Agent is unavailable",
        runtime_not_found_code="agent_unavailable",
        runtime_validation_errors=(
            SharedAgentUserCredentialRequiredError,
            SharedAgentRuntimeValidationError,
        ),
        validate_message=validate_message,
        logger=logger,
        invoke_log_message="Shared A2A agent invoke WS requested",
        invoke_log_extra_builder=lambda payload, runtime: {
            "user_id": str(current_user_id),
            "agent_id": str(agent_id),
            "agent_url": redact_url_for_logging(runtime.resolved.url),
            "query_meta": summarize_query(payload.query),
        },
        unexpected_log_message="Hub WS error",
    )
