"""A2A client unified conversation endpoints (/me/conversations)."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.schemas.session_domain import (
    SessionContinueResponse,
    SessionListResponse,
    SessionMessagesQueryRequest,
    SessionMessagesQueryResponse,
    SessionQueryRequest,
    SessionViewItem,
)
from app.services.session_hub import session_hub_service

router = StrictAPIRouter(prefix="/me/conversations", tags=["me-conversations"])

_UPSTREAM_ERRORS = {
    "upstream_unreachable",
    "upstream_http_error",
    "upstream_error",
    "runtime_invalid",
}
_FORBIDDEN_ERRORS = {"session_forbidden"}


def _status_code_for_session_error(detail: str) -> int:
    if detail == "session_not_found":
        return 404
    if detail == "message_not_found":
        return 404
    if detail == "block_not_found":
        return 404
    if detail in _FORBIDDEN_ERRORS:
        return 403
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
    items, extra, db_mutated = await session_hub_service.list_sessions(
        db,
        user_id=current_user.id,
        page=payload.page,
        size=payload.size,
        source=payload.source,
        agent_id=payload.agent_id,
    )
    if db_mutated:
        await commit_safely(db)
    return SessionListResponse(
        items=[SessionViewItem.model_validate(item) for item in items],
        pagination=extra["pagination"],
    )


@router.post(
    "/{conversation_id}/messages:query",
    response_model=SessionMessagesQueryResponse,
)
async def list_unified_session_messages(
    *,
    conversation_id: str,
    payload: SessionMessagesQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionMessagesQueryResponse:
    try:
        items, extra, db_mutated = await session_hub_service.list_messages(
            db,
            user_id=current_user.id,
            conversation_id=conversation_id,
            before=payload.before,
            limit=payload.limit,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionMessagesQueryResponse.model_validate(
        {
            "items": items,
            "pageInfo": extra["pageInfo"],
            "meta": extra["meta"],
        }
    )


@router.post("/{conversation_id}:continue", response_model=SessionContinueResponse)
async def continue_unified_session(
    *,
    conversation_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionContinueResponse:
    try:
        payload, db_mutated = await session_hub_service.continue_session(
            db,
            user_id=current_user.id,
            conversation_id=conversation_id,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionContinueResponse.model_validate(payload)


__all__ = ["router"]
