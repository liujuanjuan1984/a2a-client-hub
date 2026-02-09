"""Admin APIs for managing the global hub A2A agent catalog."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_admin_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.user import User
from app.schemas.hub_a2a_agent import (
    HubA2AAgentAdminCreate,
    HubA2AAgentAdminListResponse,
    HubA2AAgentAdminResponse,
    HubA2AAgentAdminUpdate,
    HubA2AAllowlistAddRequest,
    HubA2AAllowlistEntryResponse,
    HubA2AAllowlistListResponse,
)
from app.services.hub_a2a_agents import (
    HubA2AAgentNotFoundError,
    HubA2AAgentValidationError,
    HubA2AAllowlistConflictError,
    HubA2AUserNotFoundError,
    hub_a2a_agent_service,
)
from app.utils.logging_redaction import redact_url_for_logging
from app.utils.outbound_url import (
    OutboundURLNotAllowedError,
    validate_outbound_http_url,
)

router = StrictAPIRouter(prefix="/admin/a2a/agents", tags=["admin-a2a"])
logger = get_logger(__name__)


def _validate_card_url(value: str) -> str:
    trimmed = (value or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Card URL is required")
    parsed = urlparse(trimmed)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Card URL must be http(s)")
    try:
        validate_outbound_http_url(
            parsed.geturl(),
            allowed_hosts=settings.a2a_proxy_allowed_hosts,
            purpose="Card URL",
        )
    except OutboundURLNotAllowedError as exc:
        message = str(exc)
        if "must be http(s)" in message:
            raise HTTPException(
                status_code=400, detail="Card URL must be http(s)"
            ) from exc
        raise HTTPException(
            status_code=403, detail="Card URL host is not allowed"
        ) from exc
    return trimmed


def _build_admin_response(record) -> HubA2AAgentAdminResponse:
    agent = record.agent
    payload: dict[str, Any] = {
        "id": agent.id,
        "name": agent.name,
        "card_url": agent.card_url,
        "availability_policy": agent.availability_policy,
        "auth_type": agent.auth_type,
        "auth_header": agent.auth_header,
        "auth_scheme": agent.auth_scheme,
        "enabled": agent.enabled,
        "tags": agent.tags or [],
        "extra_headers": agent.extra_headers or {},
        "has_credential": record.has_credential,
        "token_last4": record.token_last4,
        "created_by_user_id": agent.created_by_user_id,
        "updated_by_user_id": agent.updated_by_user_id,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }
    return HubA2AAgentAdminResponse.model_validate(payload)


@router.get("", response_model=HubA2AAgentAdminListResponse)
async def list_hub_agents_admin(
    *,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
) -> HubA2AAgentAdminListResponse:
    items = await hub_a2a_agent_service.list_agents_admin(db)
    total = len(items)
    pages = (total + size - 1) // size if size else 0
    offset = (page - 1) * size
    page_items = items[offset : offset + size]
    return HubA2AAgentAdminListResponse(
        items=[_build_admin_response(item) for item in page_items],
        pagination={"page": page, "size": size, "total": total, "pages": pages},
        meta={},
    )


@router.post(
    "",
    response_model=HubA2AAgentAdminResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_hub_agent_admin(
    *,
    payload: HubA2AAgentAdminCreate,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_admin: User = Depends(get_current_admin_user),
) -> HubA2AAgentAdminResponse:
    response.headers["Cache-Control"] = "no-store"
    normalized_card_url = _validate_card_url(payload.card_url)
    logger.info(
        "Hub A2A agent create requested (admin)",
        extra={
            "admin_user_id": str(current_admin.id),
            "agent_name": payload.name,
            "card_url": redact_url_for_logging(normalized_card_url),
            "availability_policy": payload.availability_policy,
            "auth_type": payload.auth_type,
            "enabled": payload.enabled,
            "tags_count": len(payload.tags or []),
            "extra_header_keys": sorted((payload.extra_headers or {}).keys()),
        },
    )
    try:
        record = await hub_a2a_agent_service.create_agent_admin(
            db,
            admin_user_id=current_admin.id,
            name=payload.name,
            card_url=normalized_card_url,
            availability_policy=payload.availability_policy,
            auth_type=payload.auth_type,
            auth_header=payload.auth_header,
            auth_scheme=payload.auth_scheme,
            enabled=payload.enabled,
            tags=payload.tags,
            extra_headers=payload.extra_headers,
            token=payload.token,
        )
    except HubA2AAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_admin_response(record)


@router.get("/{agent_id}", response_model=HubA2AAgentAdminResponse)
async def get_hub_agent_admin(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
) -> HubA2AAgentAdminResponse:
    try:
        record = await hub_a2a_agent_service.get_agent_admin(db, agent_id=agent_id)
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _build_admin_response(record)


@router.put("/{agent_id}", response_model=HubA2AAgentAdminResponse)
async def update_hub_agent_admin(
    *,
    agent_id: UUID,
    payload: HubA2AAgentAdminUpdate,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_admin: User = Depends(get_current_admin_user),
) -> HubA2AAgentAdminResponse:
    response.headers["Cache-Control"] = "no-store"
    normalized_card_url = (
        _validate_card_url(payload.card_url) if payload.card_url else None
    )
    logger.info(
        "Hub A2A agent update requested (admin)",
        extra={
            "admin_user_id": str(current_admin.id),
            "agent_id": str(agent_id),
            "agent_name": payload.name,
            "card_url": redact_url_for_logging(normalized_card_url),
            "availability_policy": payload.availability_policy,
            "auth_type": payload.auth_type,
            "enabled": payload.enabled,
            "tags_count": len(payload.tags) if payload.tags is not None else None,
            "extra_header_keys": (
                sorted(payload.extra_headers.keys())
                if payload.extra_headers is not None
                else None
            ),
            "token_provided": payload.token is not None,
        },
    )
    try:
        record = await hub_a2a_agent_service.update_agent_admin(
            db,
            admin_user_id=current_admin.id,
            agent_id=agent_id,
            name=payload.name,
            card_url=normalized_card_url,
            availability_policy=payload.availability_policy,
            auth_type=payload.auth_type,
            auth_header=payload.auth_header,
            auth_scheme=payload.auth_scheme,
            enabled=payload.enabled,
            tags=payload.tags,
            extra_headers=payload.extra_headers,
            token=payload.token,
        )
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2AAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_admin_response(record)


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_hub_agent_admin(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_admin: User = Depends(get_current_admin_user),
) -> Response:
    try:
        await hub_a2a_agent_service.delete_agent_admin(
            db, admin_user_id=current_admin.id, agent_id=agent_id
        )
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{agent_id}/allowlist",
    response_model=HubA2AAllowlistListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_hub_agent_allowlist_admin(
    *,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
) -> HubA2AAllowlistListResponse:
    try:
        records = await hub_a2a_agent_service.list_allowlist_entries_admin(
            db, agent_id=agent_id
        )
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return HubA2AAllowlistListResponse(
        items=[
            HubA2AAllowlistEntryResponse(
                id=item.entry.id,
                agent_id=item.entry.agent_id,
                user_id=item.entry.user_id,
                user_email=item.user_email,
                user_name=item.user_name,
                created_by_user_id=item.entry.created_by_user_id,
                created_at=item.entry.created_at,
            )
            for item in records
        ]
    )


@router.post(
    "/{agent_id}/allowlist",
    response_model=HubA2AAllowlistEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_hub_agent_allowlist_admin(
    *,
    agent_id: UUID,
    payload: HubA2AAllowlistAddRequest,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_admin: User = Depends(get_current_admin_user),
) -> HubA2AAllowlistEntryResponse:
    response.headers["Cache-Control"] = "no-store"
    logger.info(
        "Hub A2A agent allowlist add requested (admin)",
        extra={
            "admin_user_id": str(current_admin.id),
            "agent_id": str(agent_id),
            "user_id": str(payload.user_id) if payload.user_id else None,
            "email": (payload.email or "").strip().lower() if payload.email else None,
        },
    )
    try:
        record = await hub_a2a_agent_service.add_allowlist_entry_admin(
            db,
            admin_user_id=current_admin.id,
            agent_id=agent_id,
            user_id=payload.user_id,
            email=payload.email,
        )
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2AAllowlistConflictError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HubA2AUserNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2AAgentValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return HubA2AAllowlistEntryResponse(
        id=record.entry.id,
        agent_id=record.entry.agent_id,
        user_id=record.entry.user_id,
        user_email=record.user_email,
        user_name=record.user_name,
        created_by_user_id=record.entry.created_by_user_id,
        created_at=record.entry.created_at,
    )


@router.delete(
    "/{agent_id}/allowlist/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_hub_agent_allowlist_admin(
    *,
    agent_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: User = Depends(get_current_admin_user),
) -> Response:
    try:
        await hub_a2a_agent_service.remove_allowlist_entry_admin(
            db, agent_id=agent_id, user_id=user_id
        )
    except HubA2AAgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
