"""User-facing routes for generic external session directories."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Depends, HTTPException, Response, status

from app.api.deps import get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.features.external_sessions.directory.registry import (
    ExternalSessionDirectoryRegistry,
    external_session_directory_registry,
)
from app.features.external_sessions.directory.schemas import (
    ExternalSessionDirectoryItem,
    ExternalSessionDirectoryListResponse,
    ExternalSessionDirectoryMeta,
    ExternalSessionDirectoryQueryRequest,
)
from app.features.external_sessions.directory.service import (
    ExternalSessionDirectoryService,
)

router = StrictAPIRouter(
    prefix="/me/a2a/external-sessions",
    tags=["external-sessions"],
)


def _resolve_external_session_directory_service(
    *,
    provider: str,
    registry: ExternalSessionDirectoryRegistry,
) -> ExternalSessionDirectoryService:
    service = registry.get_service(provider)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="external_session_provider_not_supported",
        )
    return service


@router.post(
    "/{provider}/sessions:query",
    response_model=ExternalSessionDirectoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_external_sessions_directory(
    *,
    provider: str,
    payload: ExternalSessionDirectoryQueryRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> ExternalSessionDirectoryListResponse:
    response.headers["Cache-Control"] = "no-store"
    current_user_id = cast(UUID, current_user.id)
    service = _resolve_external_session_directory_service(
        provider=provider,
        registry=external_session_directory_registry,
    )

    items, extra = await service.list_directory(
        user_id=current_user_id,
        page=payload.page,
        size=payload.size,
        refresh=payload.refresh,
    )
    pagination = extra["pagination"]
    meta = extra["meta"]
    return ExternalSessionDirectoryListResponse(
        items=[ExternalSessionDirectoryItem.model_validate(item) for item in items],
        pagination=pagination,
        meta=ExternalSessionDirectoryMeta(**meta),
    )
