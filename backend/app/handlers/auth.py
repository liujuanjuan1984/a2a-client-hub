"""Authentication handler module.

All database interactions related to authentication and user lifecycle live here so
upper layers (routers, dependencies, services) can remain persistence-agnostic.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    get_password_hash,
    validate_password_strength,
    verify_password,
)
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.utils.timezone_util import utc_now

logger = get_logger(__name__)


class AuthHandlerError(Exception):
    """Base class for authentication handler errors."""


class EmailAlreadyRegisteredError(AuthHandlerError):
    """Raised when attempting to register with an email that already exists."""


class InvalidCredentialsError(AuthHandlerError):
    """Raised when login credentials are invalid."""

    def __init__(
        self,
        message: str = "Invalid credentials",
        *,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[UUID] = None,
    ):
        super().__init__(message)
        self.metadata = metadata or {}
        self.user_id = user_id


class UserNotFoundError(AuthHandlerError):
    """Raised when a requested user does not exist or is inactive."""


class PasswordValidationError(AuthHandlerError):
    """Raised when a new password fails validation requirements."""


class PasswordReuseError(AuthHandlerError):
    """Raised when the new password matches the current one."""


class UserLockedError(AuthHandlerError):
    """Raised when a user account is temporarily locked due to failed attempts."""

    def __init__(
        self,
        *,
        user: User,
        lock_expires_at: datetime,
        seconds_remaining: int,
    ):
        super().__init__("User is temporarily locked")
        self.user_id = user.id
        self.lock_expires_at = lock_expires_at
        self.seconds_remaining = max(seconds_remaining, 0)


@dataclass
class RegistrationResult:
    """Return payload for successful registrations."""

    user: User
    is_first_user: bool
    timezone: str


def _normalize_timezone(timezone: Optional[str]) -> str:
    if isinstance(timezone, str) and timezone.strip():
        return timezone.strip()
    return "UTC"


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    name: str,
    password: str,
    timezone: Optional[str] = None,
) -> RegistrationResult:
    """Create a new user and bootstrap default data.

    Ensures idempotent behaviour by rejecting duplicate emails and centralises
    the logic for determining superuser status of the first real user.
    """

    stmt = select(User).where(User.email == email, User.disabled_at.is_(None)).limit(1)
    existing_user = (await db.execute(stmt)).scalar_one_or_none()
    if existing_user:
        raise EmailAlreadyRegisteredError("Email already registered")

    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    is_first_user = user_count == 0
    should_be_superuser = settings.first_user_superuser and is_first_user

    password_hash = get_password_hash(password)
    timezone_value = _normalize_timezone(timezone)
    user = User(
        email=email,
        name=name,
        password_hash=password_hash,
        is_superuser=should_be_superuser,
        timezone=timezone_value,
    )

    db.add(user)
    await commit_safely(db)
    await db.refresh(user)

    return RegistrationResult(
        user=user,
        is_first_user=is_first_user,
        timezone=timezone_value,
    )


async def get_active_user_by_email(
    db: AsyncSession,
    *,
    email: str,
) -> Optional[User]:
    """Fetch an active (non-disabled) user by email."""

    stmt = (
        select(User)
        .where(
            User.email == email,
            User.disabled_at.is_(None),
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    now: Optional[datetime] = None,
) -> User:
    """Validate user credentials, manage lock state, and return the active user."""

    user = await get_active_user_by_email(db, email=email)
    if not user:
        raise UserNotFoundError("Invalid credentials")

    current_time = now or utc_now()

    if user.locked_until and user.locked_until > current_time:
        seconds_remaining = int((user.locked_until - current_time).total_seconds())
        raise UserLockedError(
            user=user,
            lock_expires_at=user.locked_until,
            seconds_remaining=seconds_remaining,
        )

    if user.locked_until and user.locked_until <= current_time:
        user.reset_login_state()

    if not verify_password(password, user.password_hash):
        user.failed_login_attempts += 1
        failed_attempts = user.failed_login_attempts
        lock_expires_at = None
        if failed_attempts >= settings.auth_max_failed_login_attempts:
            lock_expires_at = current_time + timedelta(
                minutes=settings.auth_failed_login_lock_minutes
            )
            user.locked_until = lock_expires_at
            user.failed_login_attempts = 0

        db.add(user)
        metadata: Dict[str, Any] = {"failed_attempts": failed_attempts}
        if lock_expires_at:
            metadata["lock_expires_at"] = lock_expires_at.isoformat()
        raise InvalidCredentialsError(metadata=metadata, user_id=user.id)

    user.reset_login_state()
    user.last_login_at = current_time
    db.add(user)
    return user


async def change_user_password(
    db: AsyncSession,
    *,
    user: Optional[User] = None,
    user_id: Optional[UUID] = None,
    current_password: str,
    new_password: str,
) -> None:
    """Update password for the provided user after validating credentials."""

    if user is None:
        if user_id is None:
            raise ValueError("Either user or user_id must be provided")
        user = await get_active_user(db, user_id=user_id)

    if not verify_password(current_password, user.password_hash):
        raise InvalidCredentialsError("Current password is incorrect")

    if current_password == new_password:
        raise PasswordReuseError(
            "New password must be different from the current password"
        )

    is_valid, error_msg = validate_password_strength(new_password)
    if not is_valid:
        raise PasswordValidationError(error_msg or "New password is too weak")

    user.password_hash = get_password_hash(new_password)
    db.add(user)
    await commit_safely(db)


async def get_active_user(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> User:
    """Fetch an active user by id or raise."""

    stmt = select(User).where(User.id == user_id, User.disabled_at.is_(None)).limit(1)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if not user:
        raise UserNotFoundError("User not found or disabled")
    return user


async def get_user_timezone(
    db: AsyncSession,
    *,
    user_id: UUID,
    default: str = "UTC",
) -> str:
    """Return the user's configured timezone, falling back to ``default``."""

    user = await get_active_user(db, user_id=user_id)
    value = getattr(user, "timezone", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default
