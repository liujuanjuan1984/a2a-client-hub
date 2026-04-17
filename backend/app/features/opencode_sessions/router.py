"""User-facing router for the OpenCode session directory feature."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import Depends, Response, status

from app.api.deps import get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.features.opencode_sessions.schemas import (
    OpencodeSessionDirectoryItem,
    OpencodeSessionDirectoryListResponse,
    OpencodeSessionDirectoryMeta,
    OpencodeSessionDirectoryQueryRequest,
)
from app.features.opencode_sessions.service import opencode_session_directory_service

router = StrictAPIRouter(prefix="/me/a2a/opencode", tags=["opencode-sessions"])
logger = get_logger(__name__)


@router.post(
    "/sessions:query",
    response_model=OpencodeSessionDirectoryListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_opencode_sessions_directory(
    *,
    payload: OpencodeSessionDirectoryQueryRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
) -> OpencodeSessionDirectoryListResponse:
    response.headers["Cache-Control"] = "no-store"
    current_user_id = cast(UUID, current_user.id)

    items, extra = await opencode_session_directory_service.list_directory(
        user_id=current_user_id,
        page=payload.page,
        size=payload.size,
        refresh=payload.refresh,
    )
    pagination = extra["pagination"]
    meta = extra["meta"]
    return OpencodeSessionDirectoryListResponse(
        items=[OpencodeSessionDirectoryItem.model_validate(item) for item in items],
        pagination=pagination,
        meta=OpencodeSessionDirectoryMeta(**meta),
    )
