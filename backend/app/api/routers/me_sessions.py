"""A2A client unified session endpoints (/me/sessions)."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.schemas.session_domain import (
    SessionContinueResponse,
    SessionListMeta,
    SessionListResponse,
    SessionMessagesListResponse,
    SessionMessagesMeta,
    SessionMessagesQueryRequest,
    SessionQueryRequest,
    SessionViewItem,
)
from app.services.session_hub import session_hub_service

router = StrictAPIRouter(prefix="/me/sessions", tags=["me-sessions"])

_UPSTREAM_ERRORS = {
    "upstream_unreachable",
    "upstream_http_error",
    "upstream_error",
    "runtime_invalid",
}


def _status_code_for_session_error(detail: str) -> int:
    if detail == "session_not_found":
        return 404
    if detail in _UPSTREAM_ERRORS:
        return 502
    return 400


@router.post(":query", response_model=SessionListResponse)
async def list_unified_sessions(
    *,
    payload: SessionQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionListResponse:
    items, extra = await session_hub_service.list_sessions(
        db,
        user_id=current_user.id,
        page=payload.page,
        size=payload.size,
        refresh=payload.refresh,
        source=payload.source,
    )
    return SessionListResponse(
        items=[SessionViewItem.model_validate(item) for item in items],
        pagination=extra["pagination"],
        meta=SessionListMeta(**extra["meta"]),
    )


@router.post(
    "/{session_id}/messages:query",
    response_model=SessionMessagesListResponse,
)
async def list_unified_session_messages(
    *,
    session_id: str,
    payload: SessionMessagesQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionMessagesListResponse:
    try:
        items, extra = await session_hub_service.list_messages(
            db,
            user_id=current_user.id,
            session_key=session_id,
            page=payload.page,
            size=payload.size,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    await commit_safely(db)
    return SessionMessagesListResponse(
        items=items,
        pagination=extra["pagination"],
        meta=SessionMessagesMeta(**extra["meta"]),
    )


@router.post("/{session_id}:continue", response_model=SessionContinueResponse)
async def continue_unified_session(
    *,
    session_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionContinueResponse:
    try:
        payload = await session_hub_service.continue_session(
            db,
            user_id=current_user.id,
            session_key=session_id,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    await commit_safely(db)
    return SessionContinueResponse.model_validate(payload)


__all__ = ["router"]
