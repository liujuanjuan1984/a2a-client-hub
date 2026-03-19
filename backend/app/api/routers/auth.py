"""Authentication API router."""

from typing import Literal, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    create_user_access_token,
    create_user_refresh_token,
    validate_password_strength,
    verify_refresh_token,
)
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.handlers import auth as auth_handler
from app.handlers import invitations as invitation_handler
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
)

logger = get_logger(__name__)
router = StrictAPIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)

CookieSameSite = Literal["lax", "strict", "none"]


def _refresh_cookie_samesite() -> CookieSameSite:
    return cast(CookieSameSite, settings.auth_refresh_cookie_samesite)


def _serialize_user_response(
    user: User, *, timezone: str | None = None
) -> UserResponse:
    timezone_value = timezone or cast(str, user.timezone) or "UTC"
    return UserResponse(
        id=cast(UUID, user.id),
        email=cast(str, user.email),
        name=cast(str, user.name),
        is_superuser=cast(bool, user.is_superuser),
        timezone=timezone_value,
    )


@router.post(
    "/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED
)
async def register_user(
    user_data: RegisterRequest,
    db: AsyncSession = Depends(get_async_db),
) -> RegisterResponse:
    """
    Register a new user

    Args:
        user_data: User registration data
        db: Database session

    Returns:
        Created user information

    Raises:
        HTTPException: If registration fails
    """

    is_valid, error_msg = validate_password_strength(user_data.password)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    invitation = None
    invite_code = (user_data.invite_code or "").strip()

    has_existing_user = await db.scalar(select(exists().where(User.id.is_not(None))))
    invitation_required = settings.require_invitation_for_registration and bool(
        has_existing_user
    )

    if invite_code:
        try:
            invitation = await invitation_handler.validate_invitation_for_registration(
                db, code=invite_code, email=user_data.email
            )
        except invitation_handler.InvitationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )
    elif invitation_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation code is required for registration",
        )

    try:
        registration = await auth_handler.register_user(
            db,
            email=user_data.email,
            name=user_data.name,
            password=user_data.password,
            timezone=user_data.timezone,
        )
    except auth_handler.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user = registration.user
    user_id = cast(UUID, user.id)
    user_email = cast(str, user.email)

    if invitation is not None:
        await invitation_handler.mark_invitation_registered(
            db,
            invitation=invitation,
            user_id=user_id,
            memo=f"Registered by {user_email}",
        )
        await invitation_handler.revoke_other_invitations_for_email(
            db,
            email=user_email,
            exclude_invitation_id=cast(UUID, invitation.id),
            memo=f"Auto revoked after registration of {user_email}",
        )

    return RegisterResponse(
        id=user_id,
        email=user_email,
        name=cast(str, user.name),
        is_superuser=cast(bool, user.is_superuser),
        timezone=registration.timezone,
    )


@router.post("/login", response_model=LoginResponse)
async def login_user(
    login_data: LoginRequest,
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
    try:
        user = await auth_handler.authenticate_user(
            db,
            email=login_data.email,
            password=login_data.password,
        )
    except auth_handler.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    except auth_handler.UserLockedError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed login attempts. "
                "Please wait a few minutes before trying again."
            ),
        )
    except auth_handler.InvalidCredentialsError:
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    await commit_safely(db)

    user_id = cast(UUID, user.id)
    token = create_user_access_token(user_id)
    refresh_jwt = create_user_refresh_token(user_id)

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=refresh_jwt,
        httponly=True,
        secure=settings.auth_refresh_cookie_secure,
        samesite=_refresh_cookie_samesite(),
        max_age=settings.jwt_refresh_token_ttl_seconds,
        path=settings.auth_refresh_cookie_path,
    )

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        user=_serialize_user_response(user),
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

    raw_user_id = verify_refresh_token(cookie)
    if not raw_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    try:
        user_id = UUID(str(raw_user_id))
        user = await auth_handler.get_active_user(db, user_id=user_id)
    except (TypeError, ValueError, auth_handler.UserNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    persisted_user_id = cast(UUID, user.id)
    access_token = create_user_access_token(persisted_user_id)
    rotated_refresh = create_user_refresh_token(persisted_user_id)

    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=rotated_refresh,
        httponly=True,
        secure=settings.auth_refresh_cookie_secure,
        samesite=_refresh_cookie_samesite(),
        max_age=settings.jwt_refresh_token_ttl_seconds,
        path=settings.auth_refresh_cookie_path,
    )

    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        user=_serialize_user_response(user),
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
) -> UserResponse:
    """
    Get current user information

    Args:
        current_user: Current authenticated user (injected by dependency)

    Returns:
        Current user information
    """

    return _serialize_user_response(current_user)


@router.post("/password/change", response_model=PasswordChangeResponse)
async def change_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> PasswordChangeResponse:
    """Allow authenticated users to update their password."""

    try:
        await auth_handler.change_user_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except (
        auth_handler.InvalidCredentialsError,
        auth_handler.PasswordReuseError,
        auth_handler.PasswordValidationError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    logger.info("User %s successfully changed password", current_user.id)

    return PasswordChangeResponse(message="Password updated successfully")
