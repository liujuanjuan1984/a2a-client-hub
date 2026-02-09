"""User-facing OpenCode sessions directory (global list across agents)."""

from __future__ import annotations

from fastapi import Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.schemas.opencode_session_directory import (
    OpencodeSessionDirectoryListResponse,
    OpencodeSessionDirectoryMeta,
    OpencodeSessionDirectoryQueryRequest,
)
from app.services.opencode_session_directory import opencode_session_directory_service

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
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> OpencodeSessionDirectoryListResponse:
    response.headers["Cache-Control"] = "no-store"

    items, extra = await opencode_session_directory_service.list_directory(
        db,
        user_id=current_user.id,
        page=payload.page,
        size=payload.size,
        refresh=payload.refresh,
    )
    pagination = extra["pagination"]
    meta = extra["meta"]
    return OpencodeSessionDirectoryListResponse(
        items=items,
        pagination=pagination,
        meta=OpencodeSessionDirectoryMeta(**meta),
    )


__all__ = ["router"]

