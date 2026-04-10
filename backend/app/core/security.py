"""Security utilities for a2a-client-hub.

This module contains JWT token handling, password hashing, and authentication utilities.
"""

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union, cast
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.exceptions import InvalidTokenError

from app.core.config import settings
from app.utils.timezone_util import utc_now

PASSWORD_HASHER = PasswordHasher()

# Dummy hash for mitigating timing attacks during authentication
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("dummy-password-not-used")

ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


@dataclass(frozen=True)
class VerifiedJwtClaims:
    """Decoded JWT claims used by auth flows."""

    subject: str
    token_type: str
    jwt_id: str | None
    session_id: str | None
    issued_at: datetime | None
    expires_at: datetime | None
    key_id: str | None


def _jwt_signing_key() -> str:
    # Key validity is enforced in Settings() during startup.
    return cast(str, settings.jwt_private_key_pem)


def _jwt_verification_key() -> str:
    # Key validity is enforced in Settings() during startup.
    return cast(str, settings.jwt_public_key_pem)


def _jwt_verification_keys() -> dict[str, str]:
    keys = {settings.jwt_key_id: _jwt_verification_key()}
    for item in settings.jwt_previous_public_keys:
        kid = str(item["kid"]).strip()
        public_key_pem = str(item["public_key_pem"]).strip()
        if kid and public_key_pem:
            keys[kid] = public_key_pem
    return keys


def _jwt_verification_key_candidates(key_id: str | None) -> list[str]:
    verification_keys = _jwt_verification_keys()
    if isinstance(key_id, str) and key_id.strip():
        verification_key = verification_keys.get(key_id.strip())
        return [verification_key] if verification_key else []

    ordered_key_ids = [settings.jwt_key_id]
    ordered_key_ids.extend(
        str(item["kid"]).strip() for item in settings.jwt_previous_public_keys
    )
    candidates: list[str] = []
    seen_keys: set[str] = set()
    for candidate_key_id in ordered_key_ids:
        verification_key = verification_keys.get(candidate_key_id)
        if verification_key and verification_key not in seen_keys:
            candidates.append(verification_key)
            seen_keys.add(verification_key)
    return candidates


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pem_public_key_to_jwk(*, kid: str, public_key_pem: str) -> dict[str, str]:
    public_key = settings._load_jwt_public_key(public_key_pem)
    jwk: dict[str, str] = {
        "kid": kid,
        "use": "sig",
        "alg": settings.jwt_algorithm,
    }
    if isinstance(public_key, rsa.RSAPublicKey):
        rsa_numbers = public_key.public_numbers()
        jwk.update(
            {
                "kty": "RSA",
                "n": _b64url_uint(rsa_numbers.n),
                "e": _b64url_uint(rsa_numbers.e),
            }
        )
        return jwk
    if isinstance(public_key, ec.EllipticCurvePublicKey):
        ec_numbers = public_key.public_numbers()
        curve_name = public_key.curve.name
        curve_map = {
            "secp256r1": "P-256",
            "secp384r1": "P-384",
            "secp521r1": "P-521",
        }
        coordinate_size = (public_key.key_size + 7) // 8
        jwk.update(
            {
                "kty": "EC",
                "crv": curve_map[curve_name],
                "x": base64.urlsafe_b64encode(
                    ec_numbers.x.to_bytes(coordinate_size, "big")
                )
                .rstrip(b"=")
                .decode("ascii"),
                "y": base64.urlsafe_b64encode(
                    ec_numbers.y.to_bytes(coordinate_size, "big")
                )
                .rstrip(b"=")
                .decode("ascii"),
            }
        )
        return jwk
    raise ValueError("Unsupported JWT public key type")


def build_jwks_document() -> dict[str, list[dict[str, str]]]:
    """Expose active and previous public keys as a JWKS document."""

    keys = [
        _pem_public_key_to_jwk(
            kid=settings.jwt_key_id, public_key_pem=_jwt_verification_key()
        )
    ]
    for item in settings.jwt_previous_public_keys:
        keys.append(
            _pem_public_key_to_jwk(
                kid=str(item["kid"]).strip(),
                public_key_pem=str(item["public_key_pem"]).strip(),
            )
        )
    return {"keys": keys}


def _timestamp_to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return None


def create_jwt_token(
    *,
    subject: str,
    token_type: str,
    expires_in_seconds: int,
    jwt_id: str | None = None,
    session_id: str | None = None,
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
        "jti": jwt_id or uuid4().hex,
    }
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(
        payload,
        _jwt_signing_key(),
        algorithm=settings.jwt_algorithm,
        headers={"kid": settings.jwt_key_id},
    )


def verify_jwt_token_claims(
    token: str, *, expected_type: str
) -> Optional[VerifiedJwtClaims]:
    try:
        headers = jwt.get_unverified_header(token)
        key_id = headers.get("kid")
        verification_keys = _jwt_verification_key_candidates(
            str(key_id) if isinstance(key_id, str) and key_id.strip() else None
        )
        if not verification_keys:
            return None
        options = {
            "require": ["exp", "iat", "sub", "typ", "iss"],
            "verify_signature": True,
            "verify_exp": True,
        }
        payload: dict[str, Any] | None = None
        for verification_key in verification_keys:
            try:
                payload = jwt.decode(
                    token,
                    verification_key,
                    algorithms=[settings.jwt_algorithm],
                    issuer=settings.jwt_issuer,
                    options=cast(Any, options),
                )
                break
            except InvalidTokenError:
                continue
        if payload is None:
            return None
        if payload.get("typ") != expected_type:
            return None
        subject = payload.get("sub")
        if subject is None:
            return None
        return VerifiedJwtClaims(
            subject=str(subject),
            token_type=str(payload.get("typ")),
            jwt_id=str(payload.get("jti")) if payload.get("jti") else None,
            session_id=str(payload.get("sid")) if payload.get("sid") else None,
            issued_at=_timestamp_to_datetime(payload.get("iat")),
            expires_at=_timestamp_to_datetime(payload.get("exp")),
            key_id=str(key_id) if isinstance(key_id, str) and key_id.strip() else None,
        )
    except (InvalidTokenError, ValueError, TypeError):
        return None


def verify_jwt_token(token: str, *, expected_type: str) -> Optional[str]:
    claims = verify_jwt_token_claims(token, expected_type=expected_type)
    if claims is None:
        return None
    return claims.subject


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against its hash

    Args:
        plain_password: Plain text password
        hashed_password: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    try:
        return PASSWORD_HASHER.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    except (InvalidHashError, VerificationError):
        return False


def get_password_hash(password: str) -> str:
    """
    Hash a password using argon2id

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return PASSWORD_HASHER.hash(password)


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


def create_user_refresh_token(
    user_id: Union[str, UUID],
    *,
    session_id: Union[str, UUID, None] = None,
    jwt_id: str | None = None,
) -> str:
    return create_jwt_token(
        subject=str(user_id),
        token_type=REFRESH_TOKEN_TYPE,
        expires_in_seconds=settings.jwt_refresh_token_ttl_seconds,
        jwt_id=jwt_id,
        session_id=str(session_id) if session_id is not None else None,
    )


def verify_access_token(token: str) -> Optional[str]:
    return verify_jwt_token(token, expected_type=ACCESS_TOKEN_TYPE)


def verify_refresh_token(token: str) -> Optional[str]:
    return verify_jwt_token(token, expected_type=REFRESH_TOKEN_TYPE)


def verify_refresh_token_claims(token: str) -> Optional[VerifiedJwtClaims]:
    return verify_jwt_token_claims(token, expected_type=REFRESH_TOKEN_TYPE)
