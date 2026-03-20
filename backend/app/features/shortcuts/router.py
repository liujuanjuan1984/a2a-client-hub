"""Shortcut feature API router."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.features.shortcuts.schemas import (
    ShortcutCreateRequest,
    ShortcutListMeta,
    ShortcutListResponse,
    ShortcutResponse,
    ShortcutUpdateRequest,
)
from app.features.shortcuts.service import (
    ShortcutForbiddenError,
    ShortcutNotFoundError,
    ShortcutValidationError,
    shortcuts_service,
)
from app.utils.pagination import build_pagination_meta

router = StrictAPIRouter(prefix="/me/shortcuts", tags=["shortcuts"])
logger = get_logger(__name__)


def _list_shortcuts_error(
    exc: Exception, *, action: str, user_id: UUID
) -> HTTPException:
    if isinstance(exc, ShortcutValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, ShortcutNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ShortcutForbiddenError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    logger.exception(
        "Shortcut operation failed [action=%s user_id=%s]: %s",
        action,
        user_id,
        type(exc).__name__,
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Unknown error",
    )


@router.get("", response_model=ShortcutListResponse)
async def list_shortcuts(
    agent_id: UUID | None = Query(
        None, description="Optional agent ID to filter shortcuts"
    ),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ShortcutListResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        items, total = await shortcuts_service.list_shortcuts(
            db=db,
            user_id=current_user_id,
            agent_id=agent_id,
            page=page,
            size=size,
        )
    except Exception as exc:
        raise _list_shortcuts_error(
            exc,
            action="list",
            user_id=current_user_id,
        ) from exc
    return ShortcutListResponse(
        items=[ShortcutResponse.model_validate(item) for item in items],
        pagination=build_pagination_meta(total=total, page=page, size=size),
        meta=ShortcutListMeta(),
    )


@router.post(
    "",
    response_model=ShortcutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_shortcut(
    payload: ShortcutCreateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ShortcutResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        shortcut = await shortcuts_service.create_shortcut(
            db=db,
            user_id=current_user_id,
            title=payload.title,
            prompt=payload.prompt,
            order=payload.order,
            agent_id=payload.agent_id,
        )
    except Exception as exc:
        raise _list_shortcuts_error(
            exc,
            action="create",
            user_id=current_user_id,
        ) from exc
    return shortcut


@router.patch("/{shortcut_id}", response_model=ShortcutResponse)
async def update_shortcut(
    shortcut_id: UUID,
    payload: ShortcutUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> ShortcutResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        shortcut = await shortcuts_service.update_shortcut(
            db=db,
            user=current_user,
            shortcut_id=shortcut_id,
            title=payload.title,
            prompt=payload.prompt,
            order=payload.order,
            agent_id=payload.agent_id,
            clear_agent=payload.clear_agent,
        )
    except Exception as exc:
        raise _list_shortcuts_error(
            exc,
            action="update",
            user_id=current_user_id,
        ) from exc
    return shortcut


@router.delete("/{shortcut_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shortcut(
    shortcut_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> None:
    current_user_id = cast(UUID, current_user.id)
    try:
        await shortcuts_service.remove_shortcut(
            db=db,
            user=current_user,
            shortcut_id=shortcut_id,
        )
    except Exception as exc:
        raise _list_shortcuts_error(
            exc,
            action="delete",
            user_id=current_user_id,
        ) from exc
    return None
