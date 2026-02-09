"""API dependencies for a2a-client-hub.

This module contains dependency injection functions for FastAPI routes.
Supports JWT-based user authentication.
"""

from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Query, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import set_user_context
from app.core.security import verify_access_token
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.handlers import auth as auth_handler
from app.services.ws_ticket_service import WsTicketError, ws_ticket_service

# Security scheme for OpenAPI documentation
security = HTTPBearer()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Async database session dependency for FastAPI routes/services."""

    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    db: AsyncSession = Depends(get_async_db),
    token: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Get current authenticated user

    This dependency validates JWT token and returns the authenticated user.

    Args:
        db: Database session
        token: JWT token from Authorization header

    Returns:
        Current user instance

    Raises:
        HTTPException: If authentication fails
    """
    raw_user_id = verify_access_token(token.credentials)
    if not raw_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )

    try:
        user_uuid = UUID(str(raw_user_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )

    try:
        user = await auth_handler.get_active_user(
            db,
            user_id=user_uuid,
        )
        set_user_context(str(user.id))
        return user
    except auth_handler.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


def _normalize_origin(origin: str) -> str:
    return origin.strip().lower().rstrip("/")


def _is_ws_origin_allowed(origin: str | None) -> bool:
    if origin is None or origin.strip().lower() == "null":
        return not settings.ws_require_origin

    allowed = settings.ws_allowed_origins_resolved
    if not allowed:
        return not settings.ws_require_origin

    normalized_origin = _normalize_origin(origin)
    for entry in allowed:
        if entry.strip() == "*":
            return True
        if _normalize_origin(entry) == normalized_origin:
            return True
    return False


async def get_ws_ticket_user(
    *,
    websocket: WebSocket,
    scope_type: str,
    scope_id: UUID,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """
    Get current authenticated user for WebSocket connections via WS ticket.

    Args:
        websocket: WebSocket connection
        scope_type: Scope type for ticket validation
        scope_id: Scope identifier (e.g., agent_id)
        db: Database session

    Returns:
        Current user instance

    Raises:
        WebSocketException: If authentication fails
    """
    origin = websocket.headers.get("origin")
    if not _is_ws_origin_allowed(origin):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Origin not allowed"
        )

    # We extract the ticket from the Sec-WebSocket-Protocol header to avoid
    # leaking it in URL query parameters.
    ticket = None
    subprotocols = websocket.headers.get("sec-websocket-protocol")
    if subprotocols:
        for proto in subprotocols.split(","):
            candidate = proto.strip()
            # tickets are generated with urlsafe_token (base64-ish) and length >= 16
            if len(candidate) >= 16:
                ticket = candidate
                break

    if not ticket:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Ticket is required"
        )

    try:
        consumed = await ws_ticket_service.consume_ticket(
            db,
            token=ticket,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    except WsTicketError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason=str(exc)
        ) from exc

    try:
        user = await auth_handler.get_active_user(
            db,
            user_id=consumed.user_id,
        )
        set_user_context(str(user.id))
        return user
    except auth_handler.UserNotFoundError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc),
        ) from exc


async def get_ws_ticket_user_me(
    *,
    websocket: WebSocket,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    return await get_ws_ticket_user(
        websocket=websocket,
        scope_type="me_a2a_agent",
        scope_id=agent_id,
        db=db,
    )


async def get_ws_ticket_user_hub(
    *,
    websocket: WebSocket,
    agent_id: UUID,
    db: AsyncSession = Depends(get_async_db),
) -> User:
    return await get_ws_ticket_user(
        websocket=websocket,
        scope_type="hub_a2a_agent",
        scope_id=agent_id,
        db=db,
    )


def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current authenticated user and check for superuser privileges

    Args:
        current_user: Current authenticated user from get_current_user dependency

    Returns:
        User instance if the user is a superuser

    Raises:
        HTTPException: If the user is not a superuser
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user
