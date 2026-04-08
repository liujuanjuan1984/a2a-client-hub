"""Authentication feature API router."""

import asyncio
import time
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
    build_jwks_document,
    create_user_access_token,
    create_user_refresh_token,
    validate_password_strength,
    verify_refresh_token_claims,
)
from app.db.locking import set_postgres_local_timeouts
from app.db.models.user import User
from app.db.transaction import commit_safely, rollback_safely
from app.features.auth import service as auth_service
from app.features.auth.audit_service import record_auth_event
from app.features.auth.rate_limit import auth_rate_limiter
from app.features.auth.request_context import (
    enforce_trusted_cookie_origin,
    get_client_ip,
    get_user_agent,
)
from app.features.auth.schemas import (
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
)
from app.features.auth.session_service import (
    RefreshSessionNotFoundError,
    RefreshSessionReplayError,
    RefreshSessionRevokedError,
    bootstrap_legacy_refresh_session,
    create_refresh_session,
    revoke_all_refresh_sessions_for_user,
    revoke_refresh_session,
    rotate_refresh_session,
)
from app.features.invitations import service as invitation_service
from app.runtime.ops_metrics import ops_metrics

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


def _raise_rate_limited(retry_after_seconds: int) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many auth attempts. Please retry later.",
        headers={"Retry-After": str(retry_after_seconds)},
    )


def _enforce_login_rate_limit(*, request: Request, email: str) -> None:
    client_ip = get_client_ip(request) or "unknown"
    decision = auth_rate_limiter.check_and_record(
        scope="auth_login_ip_email",
        key=f"{client_ip}:{email.strip().lower()}",
        max_attempts=settings.auth_login_rate_limit_max_attempts,
        window_seconds=settings.auth_login_rate_limit_window_seconds,
    )
    if not decision.allowed:
        _raise_rate_limited(decision.retry_after_seconds)


def _enforce_refresh_rate_limit(
    *,
    request: Request,
    subject: str | None,
    session_id: str | None,
) -> None:
    client_ip = get_client_ip(request) or "unknown"
    scopes = [f"ip:{client_ip}"]
    if session_id:
        scopes.append(f"ip:{client_ip}:sid:{session_id}")
    elif subject:
        scopes.append(f"ip:{client_ip}:sub:{subject}")

    for key in scopes:
        decision = auth_rate_limiter.check_and_record(
            scope="auth_refresh",
            key=key,
            max_attempts=settings.auth_refresh_rate_limit_max_attempts,
            window_seconds=settings.auth_refresh_rate_limit_window_seconds,
        )
        if not decision.allowed:
            _raise_rate_limited(decision.retry_after_seconds)


def _refresh_log_payload(
    *,
    request: Request,
    user_id: UUID | None,
    session_id: UUID | None,
    phase_timings_ms: dict[str, float],
    outcome: str,
    total_ms: float,
) -> dict[str, object]:
    return {
        "phase": "auth_refresh",
        "auth_refresh_outcome": outcome,
        "auth_refresh_total_ms": round(total_ms, 3),
        "auth_refresh_timings_ms": {
            key: round(value, 3) for key, value in phase_timings_ms.items()
        },
        "client_ip": get_client_ip(request),
        "user_agent": get_user_agent(request),
        "db_pool_checked_out": ops_metrics.snapshot().get("db_pool_checked_out"),
        "refresh_session_id": str(session_id) if session_id else None,
        "refresh_user_id": str(user_id) if user_id else None,
    }


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
            invitation = await invitation_service.validate_invitation_for_registration(
                db, code=invite_code, email=user_data.email
            )
        except invitation_service.InvitationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )
    elif invitation_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation code is required for registration",
        )

    try:
        registration = await auth_service.register_user(
            db,
            email=user_data.email,
            name=user_data.name,
            password=user_data.password,
            timezone=user_data.timezone,
        )
    except auth_service.EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    user_id = registration.user_id
    user_email = registration.email

    if invitation is not None:
        await invitation_service.mark_invitation_registered(
            db,
            invitation=invitation,
            user_id=user_id,
            memo=f"Registered by {user_email}",
        )
        await invitation_service.revoke_other_invitations_for_email(
            db,
            email=user_email,
            exclude_invitation_id=cast(UUID, invitation.id),
            memo=f"Auto revoked after registration of {user_email}",
        )
    await commit_safely(db)

    return RegisterResponse(
        id=user_id,
        email=user_email,
        name=registration.name,
        is_superuser=registration.is_superuser,
        timezone=registration.timezone,
    )


@router.post("/login", response_model=LoginResponse)
async def login_user(
    request: Request,
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
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    try:
        _enforce_login_rate_limit(request=request, email=login_data.email)
    except HTTPException as exc:
        await record_auth_event(
            db,
            event_type="login_blocked",
            outcome="blocked",
            email=login_data.email,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "rate_limited"},
        )
        await commit_safely(db)
        raise exc

    try:
        user = await auth_service.authenticate_user(
            db,
            email=login_data.email,
            password=login_data.password,
        )
    except auth_service.UserNotFoundError:
        await record_auth_event(
            db,
            event_type="login_failed",
            outcome="failed",
            email=login_data.email,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "user_not_found"},
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    except auth_service.UserLockedError as exc:
        await record_auth_event(
            db,
            event_type="login_blocked",
            outcome="blocked",
            user_id=cast(UUID, exc.user_id),
            email=login_data.email,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={
                "reason": "user_locked",
                "seconds_remaining": exc.seconds_remaining,
            },
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many failed login attempts. "
                "Please wait a few minutes before trying again."
            ),
        )
    except auth_service.InvalidCredentialsError as exc:
        await record_auth_event(
            db,
            event_type="login_failed",
            outcome="failed",
            user_id=exc.user_id,
            email=login_data.email,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata=exc.metadata or {"reason": "invalid_credentials"},
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    user_id = cast(UUID, user.id)
    rotation = await create_refresh_session(
        db,
        user_id=user_id,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    session_id = cast(UUID, rotation.session.id)
    token = create_user_access_token(user_id)
    refresh_jwt = create_user_refresh_token(
        user_id,
        session_id=session_id,
        jwt_id=rotation.next_jti,
    )
    await record_auth_event(
        db,
        event_type="login_success",
        outcome="success",
        user_id=user_id,
        session_id=session_id,
        session_jti=rotation.next_jti,
        email=cast(str, user.email),
        ip_address=client_ip,
        user_agent=user_agent,
    )
    await commit_safely(db)

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

    enforce_trusted_cookie_origin(request)

    request_started = time.perf_counter()
    phase_started = request_started
    phase_timings_ms: dict[str, float] = {}
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    cookie = request.cookies.get(settings.auth_refresh_cookie_name)
    if not cookie:
        await record_auth_event(
            db,
            event_type="refresh_failed",
            outcome="failed",
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "missing_cookie"},
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )

    claims = verify_refresh_token_claims(cookie)
    phase_timings_ms["jwt_verify"] = (time.perf_counter() - phase_started) * 1000.0
    phase_started = time.perf_counter()
    if not claims:
        await record_auth_event(
            db,
            event_type="refresh_failed",
            outcome="failed",
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "invalid_refresh_token"},
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    try:
        _enforce_refresh_rate_limit(
            request=request,
            subject=claims.subject,
            session_id=claims.session_id,
        )
    except HTTPException as exc:
        await record_auth_event(
            db,
            event_type="refresh_blocked",
            outcome="blocked",
            session_jti=claims.jwt_id,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "rate_limited", "session_id": claims.session_id},
        )
        await commit_safely(db)
        raise exc

    try:
        user_id = UUID(claims.subject)
    except (TypeError, ValueError) as exc:
        await record_auth_event(
            db,
            event_type="refresh_failed",
            outcome="failed",
            session_jti=claims.jwt_id,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={"reason": "invalid_subject"},
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    rotation = None
    user: User | None = None
    try:
        async with asyncio.timeout(settings.auth_refresh_db_timeout_seconds):
            await set_postgres_local_timeouts(
                db,
                statement_timeout_ms=int(
                    settings.auth_refresh_db_timeout_seconds * 1000
                ),
            )
            if claims.session_id:
                rotation = await rotate_refresh_session(
                    db,
                    user_id=user_id,
                    session_id=UUID(claims.session_id),
                    presented_jti=claims.jwt_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            else:
                rotation = await bootstrap_legacy_refresh_session(
                    db,
                    user_id=user_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            phase_timings_ms["session_state"] = (
                time.perf_counter() - phase_started
            ) * 1000.0
            phase_started = time.perf_counter()
            user = await auth_service.get_active_user(db, user_id=user_id)
            phase_timings_ms["user_lookup"] = (
                time.perf_counter() - phase_started
            ) * 1000.0
    except TimeoutError as exc:
        await rollback_safely(db)
        total_ms = (time.perf_counter() - request_started) * 1000.0
        warning_payload = _refresh_log_payload(
            request=request,
            user_id=user_id,
            session_id=None,
            phase_timings_ms=phase_timings_ms,
            outcome="timeout",
            total_ms=total_ms,
        )
        logger.warning(
            "Auth refresh fast-failed due to database timeout.",
            extra=warning_payload,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refresh is temporarily unavailable. Please retry.",
            headers={"Retry-After": "2"},
        ) from exc
    except (
        TypeError,
        ValueError,
        auth_service.UserNotFoundError,
        RefreshSessionNotFoundError,
        RefreshSessionRevokedError,
        RefreshSessionReplayError,
    ) as exc:
        outcome = "revoked" if isinstance(exc, RefreshSessionReplayError) else "failed"
        await record_auth_event(
            db,
            event_type="refresh_failed",
            outcome=outcome,
            user_id=user_id,
            session_id=cast(UUID, rotation.session.id) if rotation else None,
            session_jti=claims.jwt_id,
            ip_address=client_ip,
            user_agent=user_agent,
            metadata={
                "reason": exc.__class__.__name__,
                "session_id": claims.session_id,
            },
        )
        await commit_safely(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from exc

    assert rotation is not None
    assert user is not None
    persisted_user_id = cast(UUID, user.id)
    refreshed_session_id = cast(UUID, rotation.session.id)
    access_token = create_user_access_token(persisted_user_id)
    rotated_refresh = create_user_refresh_token(
        persisted_user_id,
        session_id=refreshed_session_id,
        jwt_id=rotation.next_jti,
    )
    total_ms = (time.perf_counter() - request_started) * 1000.0
    await record_auth_event(
        db,
        event_type="refresh_success",
        outcome="success",
        user_id=persisted_user_id,
        session_id=refreshed_session_id,
        session_jti=rotation.next_jti,
        email=cast(str, user.email),
        ip_address=client_ip,
        user_agent=user_agent,
        metadata={"legacy_bootstrap": rotation.was_legacy_bootstrap},
    )
    await commit_safely(db)

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
    log_payload = _refresh_log_payload(
        request=request,
        user_id=persisted_user_id,
        session_id=refreshed_session_id,
        phase_timings_ms=phase_timings_ms,
        outcome="success",
        total_ms=total_ms,
    )
    if total_ms >= settings.auth_refresh_slow_log_threshold_ms:
        logger.warning("Auth refresh completed slowly.", extra=log_payload)
    else:
        logger.info("Auth refresh completed.", extra=log_payload)

    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_ttl_seconds,
        user=_serialize_user_response(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_user(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Clear refresh cookie and revoke the current refresh session when present."""

    enforce_trusted_cookie_origin(request)
    client_ip = get_client_ip(request)
    user_agent = get_user_agent(request)
    cookie = request.cookies.get(settings.auth_refresh_cookie_name)
    claims = verify_refresh_token_claims(cookie) if cookie else None
    user_id: UUID | None = None
    session_id: UUID | None = None
    if claims is not None:
        try:
            user_id = UUID(claims.subject)
        except (TypeError, ValueError):
            user_id = None
        try:
            session_id = UUID(claims.session_id) if claims.session_id else None
        except (TypeError, ValueError):
            session_id = None
        if user_id and session_id:
            await revoke_refresh_session(
                db,
                session_id=session_id,
                user_id=user_id,
                reason="logout",
                client_ip=client_ip,
                user_agent=user_agent,
            )
        await record_auth_event(
            db,
            event_type="logout",
            outcome="revoked",
            user_id=user_id,
            session_id=session_id,
            session_jti=claims.jwt_id,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        await commit_safely(db)
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
    request: Request,
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> PasswordChangeResponse:
    """Allow authenticated users to update their password."""

    try:
        await auth_service.change_user_password(
            db,
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except (
        auth_service.InvalidCredentialsError,
        auth_service.PasswordReuseError,
        auth_service.PasswordValidationError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    revoked_sessions = await revoke_all_refresh_sessions_for_user(
        db,
        user_id=cast(UUID, current_user.id),
        reason="password_changed",
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    await record_auth_event(
        db,
        event_type="password_changed",
        outcome="success",
        user_id=cast(UUID, current_user.id),
        email=cast(str, current_user.email),
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        metadata={"revoked_sessions": revoked_sessions},
    )
    await commit_safely(db)
    logger.info(
        "User %s successfully changed password",
        current_user.id,
        extra={"revoked_sessions": revoked_sessions},
    )

    return PasswordChangeResponse(message="Password updated successfully")


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all_sessions(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Revoke every active refresh session for the authenticated user."""

    revoked_sessions = await revoke_all_refresh_sessions_for_user(
        db,
        user_id=cast(UUID, current_user.id),
        reason="logout_all",
        client_ip=get_client_ip(request),
        user_agent=get_user_agent(request),
    )
    await record_auth_event(
        db,
        event_type="logout_all",
        outcome="revoked",
        user_id=cast(UUID, current_user.id),
        email=cast(str, current_user.email),
        ip_address=get_client_ip(request),
        user_agent=get_user_agent(request),
        metadata={"revoked_sessions": revoked_sessions},
    )
    await commit_safely(db)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        key=settings.auth_refresh_cookie_name,
        path=settings.auth_refresh_cookie_path,
    )


@router.get("/.well-known/jwks.json")
async def get_jwks() -> dict[str, list[dict[str, str]]]:
    """Expose active and previous JWT verification keys as JWKS."""

    return build_jwks_document()
