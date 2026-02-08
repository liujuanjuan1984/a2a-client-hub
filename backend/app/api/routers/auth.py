"""
Authentication API Router

This module contains API endpoints for user authentication (login/refresh/logout/me).
"""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_user_access_token,
    create_user_refresh_token,
    verify_refresh_token,
)
from app.db.models.user import User
from app.handlers import auth as auth_handler
from app.handlers import user_preferences
from app.schemas.auth import LoginRequest, LoginResponse, RefreshResponse, UserResponse
from app.services.user_activity import log_activity

logger = get_logger(__name__)
router = StrictAPIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)


@router.post("/login", response_model=LoginResponse)
async def login_user(
    login_data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
) -> LoginResponse:
    """
    Login user and return access token

    Args:
        login_data: User login credentials
        db: Database session

    Returns:
        Access token and user information

    Raises:
        HTTPException: If login fails
    """
    request_metadata = _build_activity_metadata(request, email=login_data.email)

    try:
        user = await auth_handler.authenticate_user(
            db,
            email=login_data.email,
            password=login_data.password,
        )
    except auth_handler.UserNotFoundError:
        await log_activity(
            db,
            user_id=None,
            event_type="auth.login",
            status="failed",
            metadata={**request_metadata, "reason": "user_not_found"},
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    except auth_handler.UserLockedError as exc:
        await log_activity(
            db,
            user_id=exc.user_id,
            event_type="auth.login",
            status="blocked",
            metadata={
                **request_metadata,
                "lock_expires_at": exc.lock_expires_at.isoformat(),
                "lock_seconds_remaining": exc.seconds_remaining,
            },
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed login attempts. "
                "Please wait a few minutes before trying again."
            ),
        )
    except auth_handler.InvalidCredentialsError as exc:
        failure_metadata = {**request_metadata, **getattr(exc, "metadata", {})}
        failure_metadata.setdefault("reason", "invalid_credentials")
        await log_activity(
            db,
            user_id=getattr(exc, "user_id", None),
            event_type="auth.login",
            status="failed",
            metadata=failure_metadata,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    await log_activity(
        db,
        user_id=user.id,
        event_type="auth.login",
        status="success",
        metadata=request_metadata,
    )
    await db.commit()

    token = create_user_access_token(user.id)
    refresh_jwt = create_user_refresh_token(user.id)
    timezone_value, _ = await auth_handler.resolve_user_timezone(db, user_id=user.id)

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=refresh_jwt,
        httponly=True,
        secure=settings.auth_refresh_cookie_secure,
        samesite=settings.auth_refresh_cookie_samesite,
        max_age=settings.jwt_refresh_token_ttl_seconds,
        path=settings.auth_refresh_cookie_path,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_superuser=user.is_superuser,
            timezone=timezone_value,
        ),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
) -> RefreshResponse:
    """Refresh access token using HttpOnly refresh cookie."""

    cookie = request.cookies.get(settings.auth_refresh_cookie_name)
    if not cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    user_id = verify_refresh_token(cookie)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    try:
        user = await auth_handler.get_active_user(db, user_id=user_id)
    except auth_handler.UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    access_token = create_user_access_token(user.id)
    rotated_refresh = create_user_refresh_token(user.id)
    timezone_value, _ = await auth_handler.resolve_user_timezone(db, user_id=user.id)

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=rotated_refresh,
        httponly=True,
        secure=settings.auth_refresh_cookie_secure,
        samesite=settings.auth_refresh_cookie_samesite,
        max_age=settings.jwt_refresh_token_ttl_seconds,
        path=settings.auth_refresh_cookie_path,
    )

    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            is_superuser=user.is_superuser,
            timezone=timezone_value,
        ),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_user(response: Response) -> None:
    """Clear refresh cookie (client still needs to drop the access token)."""

    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        path=settings.auth_refresh_cookie_path,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserResponse:
    """
    Get current user information

    Args:
        current_user: Current authenticated user (injected by dependency)

    Returns:
        Current user information
    """

    timezone_value = await user_preferences.get_user_timezone(
        db,
        user_id=current_user.id,
        default="UTC",
    )
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        name=current_user.name,
        is_superuser=current_user.is_superuser,
        timezone=timezone_value,
    )


def _build_activity_metadata(
    request: Request,
    *,
    email: Optional[str] = None,
    user_id: Optional[UUID] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose a metadata payload shared by auth events."""

    ip = _extract_client_ip(request)
    user_agent = request.headers.get("user-agent")
    request_id = getattr(request.state, "request_id", None)
    payload: Dict[str, Any] = {}
    if email:
        payload["email"] = email
    if user_id:
        payload["user_id"] = str(user_id)
    if ip:
        payload["ip"] = ip
    if user_agent:
        payload["user_agent"] = user_agent
    if request_id:
        payload["request_id"] = request_id
    if extra:
        payload.update(extra)
    return payload


def _extract_client_ip(request: Request) -> Optional[str]:
    """Best-effort extraction of the originating IP address."""

    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip
    if request.client and request.client.host:
        return request.client.host
    return None
