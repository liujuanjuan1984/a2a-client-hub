"""API dependencies for a2a-client-hub.

This module contains dependency injection functions for FastAPI routes.
Supports JWT-based user authentication.
"""

import re
from dataclasses import dataclass
from typing import AsyncGenerator, cast
from uuid import UUID

from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.retry_after import append_retry_after_hint
from app.core.config import settings
from app.core.logging import get_logger, set_actor_context, set_user_context
from app.core.security import ACCESS_TOKEN_TYPE, verify_jwt_token
from app.db.locking import (
    RetryableDbLockError,
    RetryableDbQueryTimeoutError,
)
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.db.transaction import cleanup_session_safely, run_with_new_session
from app.features.auth import service as auth_service
from app.features.hub_assistant_shared.actor_context import (
    HubAssistantActorContext,
    HubAssistantActorType,
    HubAssistantAuthorizationError,
    build_hub_assistant_actor_context,
)
from app.features.hub_assistant_shared.hub_assistant_web_agent import (
    HubAssistantWebAgentRuntime,
    build_hub_assistant_web_agent_runtime,
)
from app.features.hub_assistant_shared.tool_gateway import (
    HubAssistantSurface,
    HubAssistantToolGateway,
)
from app.runtime.ops_metrics import ops_metrics
from app.runtime.ws_ticket import (
    WsTicketError,
    ws_ticket_service,
)

# Security scheme for OpenAPI documentation
security = HTTPBearer()

_WS_TICKET_RE = re.compile(r"^[A-Za-z0-9_-]+$")
logger = get_logger(__name__)


@dataclass(frozen=True)
class WsProtocolSelection:
    ticket: str | None
    accepted_subprotocol: str | None


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Async database session dependency for FastAPI routes/services."""

    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await cleanup_session_safely(session)


async def get_current_user(
    token: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """
    Get current authenticated user

    This dependency validates JWT token and returns the authenticated user.

    Args:
        token: JWT token from Authorization header

    Returns:
        Current user instance

    Raises:
        HTTPException: If authentication fails
    """
    raw_user_id = verify_jwt_token(token.credentials, expected_type=ACCESS_TOKEN_TYPE)
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

        async def _load_current_user(db: AsyncSession) -> User:
            return await auth_service.get_active_user(
                db,
                user_id=user_uuid,
            )

        user = await run_with_new_session(
            _load_current_user,
            session_factory=AsyncSessionLocal,
        )
        set_user_context(str(user.id))
        set_actor_context(
            principal_user_id=str(user.id),
            actor_type=HubAssistantActorType.HUMAN_API.value,
            admin_mode=False,
        )
        return user
    except auth_service.UserNotFoundError as exc:
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


def _parse_ws_protocol_selection(
    *,
    subprotocol_header: str | None,
    allowed_subprotocols: tuple[str, ...] = (),
) -> WsProtocolSelection:
    if not subprotocol_header:
        return WsProtocolSelection(ticket=None, accepted_subprotocol=None)

    expected_len = settings.ws_ticket_length
    allowed = {item.strip() for item in allowed_subprotocols if item.strip()}
    ticket: str | None = None
    accepted_subprotocol: str | None = None

    for raw_value in subprotocol_header.split(","):
        candidate = raw_value.strip()
        if not candidate:
            continue
        if (
            ticket is None
            and len(candidate) == expected_len
            and _WS_TICKET_RE.match(candidate)
        ):
            ticket = candidate
            continue
        if accepted_subprotocol is None and candidate in allowed:
            accepted_subprotocol = candidate

    return WsProtocolSelection(
        ticket=ticket,
        accepted_subprotocol=accepted_subprotocol,
    )


async def get_ws_ticket_user(
    *,
    websocket: WebSocket,
    scope_type: str,
    scope_id: UUID,
) -> User:
    """
    Get current authenticated user for WebSocket connections via WS ticket.

    Args:
        websocket: WebSocket connection
        scope_type: Scope type for ticket validation
        scope_id: Scope identifier (e.g., agent_id)

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

    # Extract the auth ticket from Sec-WebSocket-Protocol without treating it as
    # a negotiated application subprotocol.
    protocol_selection = _parse_ws_protocol_selection(
        subprotocol_header=websocket.headers.get("sec-websocket-protocol"),
        allowed_subprotocols=("a2a-invoke-v1",),
    )
    ticket = protocol_selection.ticket

    if not ticket:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Ticket is required"
        )

    try:

        async def _consume_ws_ticket_user(db: AsyncSession) -> User:
            consumed = await ws_ticket_service.consume_ticket(
                db,
                token=ticket,
                scope_type=scope_type,
                scope_id=scope_id,
            )
            consumed_user_id = cast(UUID, consumed.user_id)
            user = await auth_service.get_active_user(
                db,
                user_id=consumed_user_id,
            )
            return user

        user = await run_with_new_session(
            _consume_ws_ticket_user,
            session_factory=AsyncSessionLocal,
        )
        websocket.state.selected_subprotocol = protocol_selection.accepted_subprotocol
        set_user_context(str(user.id))
        set_actor_context(
            principal_user_id=str(user.id),
            actor_type=HubAssistantActorType.HUMAN_API.value,
            admin_mode=False,
        )
        return user
    except RetryableDbLockError as exc:
        ops_metrics.increment_ws_ticket_lock_conflicts()
        logger.warning(
            "WS ticket consume deferred due to DB lock contention for scope_type=%s scope_id=%s kind=%s",
            scope_type,
            scope_id,
            exc.kind.value,
            exc_info=exc,
            extra={
                "phase": "ws_ticket_auth",
                "scope_type": scope_type,
                "scope_id": str(scope_id),
                "ws_ticket_conflict": True,
                "db_lock_failure_kind": exc.kind.value,
            },
        )
        raise WebSocketException(
            code=status.WS_1013_TRY_AGAIN_LATER,
            reason=append_retry_after_hint(str(exc)),
        ) from exc
    except RetryableDbQueryTimeoutError as exc:
        ops_metrics.increment_ws_ticket_query_timeouts()
        logger.warning(
            "WS ticket consume deferred due to DB query timeout for scope_type=%s scope_id=%s",
            scope_type,
            scope_id,
            exc_info=exc,
            extra={
                "phase": "ws_ticket_auth",
                "scope_type": scope_type,
                "scope_id": str(scope_id),
                "ws_ticket_query_timeout": True,
            },
        )
        raise WebSocketException(
            code=status.WS_1013_TRY_AGAIN_LATER,
            reason=append_retry_after_hint(str(exc)),
        ) from exc
    except WsTicketError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason=str(exc)
        ) from exc
    except auth_service.UserNotFoundError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc),
        ) from exc


async def get_ws_ticket_user_me(
    *,
    websocket: WebSocket,
    agent_id: UUID,
) -> User:
    return await get_ws_ticket_user(
        websocket=websocket,
        scope_type="me_a2a_agent",
        scope_id=agent_id,
    )


async def get_ws_ticket_user_hub(
    *,
    websocket: WebSocket,
    agent_id: UUID,
) -> User:
    return await get_ws_ticket_user(
        websocket=websocket,
        scope_type="hub_a2a_agent",
        scope_id=agent_id,
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
    set_actor_context(
        principal_user_id=str(current_user.id),
        actor_type=HubAssistantActorType.HUMAN_API.value,
        admin_mode=True,
    )
    return current_user


def get_current_hub_assistant_actor(
    current_user: User = Depends(get_current_user),
) -> HubAssistantActorContext:
    """Resolve the default authenticated actor for Hub Assistant operations."""

    actor = build_hub_assistant_actor_context(
        user=current_user,
        actor_type=HubAssistantActorType.HUMAN_API,
    )
    set_actor_context(
        principal_user_id=str(actor.principal_user_id),
        actor_type=actor.actor_type.value,
        admin_mode=actor.admin_mode,
    )
    return actor


def get_current_hub_assistant_admin_actor(
    current_user: User = Depends(get_current_user),
) -> HubAssistantActorContext:
    """Resolve an admin-mode actor for Hub Assistant operations."""

    try:
        actor = build_hub_assistant_actor_context(
            user=current_user,
            actor_type=HubAssistantActorType.HUMAN_API,
            admin_mode=True,
        )
    except HubAssistantAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    set_actor_context(
        principal_user_id=str(actor.principal_user_id),
        actor_type=actor.actor_type.value,
        admin_mode=actor.admin_mode,
    )
    return actor


def get_current_hub_assistant_tool_gateway(
    actor: HubAssistantActorContext = Depends(get_current_hub_assistant_actor),
) -> HubAssistantToolGateway:
    """Resolve the default Hub Assistant authorization gateway."""

    return HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)


def get_current_hub_assistant_admin_tool_gateway(
    actor: HubAssistantActorContext = Depends(get_current_hub_assistant_admin_actor),
) -> HubAssistantToolGateway:
    """Resolve the admin-mode Hub Assistant authorization gateway."""

    return HubAssistantToolGateway(actor, surface=HubAssistantSurface.REST)


def get_current_hub_assistant_web_agent_runtime(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HubAssistantWebAgentRuntime:
    """Resolve the Hub Assistant web-agent runtime for Hub Assistant operations."""

    runtime = build_hub_assistant_web_agent_runtime(
        db=db,
        current_user=current_user,
    )
    set_actor_context(
        principal_user_id=str(runtime.actor.principal_user_id),
        actor_type=runtime.actor.actor_type.value,
        admin_mode=runtime.actor.admin_mode,
    )
    return runtime
