"""Issue WebSocket ticket route helpers for invoke flows."""

from __future__ import annotations

from typing import Any, Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.retry_after import db_busy_retry_after_headers
from app.db.locking import (
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.schemas.ws_ticket import WsTicketResponse


async def run_issue_ws_ticket_route(
    *,
    db: AsyncSession,
    user_id: UUID,
    scope_type: str,
    scope_id: UUID,
    ensure_access: Callable[[], Awaitable[Any]],
    not_found_errors: tuple[type[Exception], ...],
    not_found_status_code: int,
    not_found_detail: str | Callable[[Exception], str],
    issue_ticket_fn: Callable[..., Awaitable[Any]],
) -> WsTicketResponse:
    try:
        await ensure_access()
    except not_found_errors as exc:
        detail = (
            not_found_detail(exc) if callable(not_found_detail) else not_found_detail
        )
        raise HTTPException(status_code=not_found_status_code, detail=detail) from exc

    try:
        issued = await issue_ticket_fn(
            db,
            user_id=user_id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    except RetryableDbLockError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except RetryableDbQueryTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers=db_busy_retry_after_headers(),
        ) from exc
    return WsTicketResponse(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=issued.expires_in,
    )
