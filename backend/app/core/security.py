"""Security utilities for a2a-client-hub.

This module contains JWT token handling, password hashing, and authentication utilities.
"""

from datetime import timedelta
from typing import Optional, Union, cast
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import settings
from app.utils.timezone_util import utc_now

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dummy hash for mitigating timing attacks during authentication
DUMMY_PASSWORD_HASH = "$2b$12$KIXeW.1LzBwvS./Hk.yQ1..E3.eD/.hLwQcE/M1zQ3X.qC0TqYFOW"

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def _jwt_signing_key() -> str:
    # Key validity is enforced in Settings() during startup.
    return cast(str, settings.jwt_private_key_pem)


def _jwt_verification_key() -> str:
    # Key validity is enforced in Settings() during startup.
    return cast(str, settings.jwt_public_key_pem)


def create_jwt_token(
    *,
    subject: str,
    token_type: str,
    expires_in_seconds: int,
) -> str:
    now = utc_now()
    expire = now + timedelta(seconds=expires_in_seconds)
    payload = {
        "sub": subject,
        "typ": token_type,
        "iat": now,
        "exp": expire,
        "iss": settings.jwt_issuer,
        # Ensure tokens are unique even when refreshed within the same second.
        "jti": uuid4().hex,
    }
    return jwt.encode(
        payload,
        _jwt_signing_key(),
        algorithm=settings.jwt_algorithm,
    )


def verify_jwt_token(token: str, *, expected_type: str) -> Optional[str]:
    try:
        options = {
            "require": ["exp", "iat", "sub", "typ", "iss"],
            "verify_signature": True,
            "verify_exp": True,
        }
        payload = jwt.decode(
            token,
            _jwt_verification_key(),
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options=options,
        )
        if payload.get("typ") != expected_type:
            return None
        subject = payload.get("sub")
        if subject is None:
            return None
        return str(subject)
    except (InvalidTokenError, ValueError, TypeError):
        return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its hash

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password using bcrypt

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength according to requirements

    Requirements:
    - At least 8 characters
    - Contains uppercase letter
    - Contains lowercase letter
    - Contains digit
    - Contains special character

    Args:
        password: Plain text password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() and not c.isspace() for c in password)

    if not has_upper:
        return False, "Password must contain at least one uppercase letter"
    if not has_lower:
        return False, "Password must contain at least one lowercase letter"
    if not has_digit:
        return False, "Password must contain at least one digit"
    if not has_special:
        return False, "Password must contain at least one special character"

    return True, ""


def create_user_token(user_id: Union[str, UUID]) -> str:
    return create_user_access_token(user_id)


def create_user_access_token(user_id: Union[str, UUID]) -> str:
    return create_jwt_token(
        subject=str(user_id),
        token_type=ACCESS_TOKEN_TYPE,
        expires_in_seconds=settings.jwt_access_token_ttl_seconds,
    )


def create_user_refresh_token(user_id: Union[str, UUID]) -> str:
    return create_jwt_token(
        subject=str(user_id),
        token_type=REFRESH_TOKEN_TYPE,
        expires_in_seconds=settings.jwt_refresh_token_ttl_seconds,
    )


def verify_access_token(token: str) -> Optional[str]:
    return verify_jwt_token(token, expected_type=ACCESS_TOKEN_TYPE)


def verify_refresh_token(token: str) -> Optional[str]:
    return verify_jwt_token(token, expected_type=REFRESH_TOKEN_TYPE)
