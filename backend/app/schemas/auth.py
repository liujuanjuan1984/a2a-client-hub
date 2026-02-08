"""
Authentication schemas for Common Compass Backend

This module contains Pydantic schemas for user authentication requests and responses.
"""

from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
)


class RegisterRequest(BaseModel):
    """User registration request schema"""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(
        ..., min_length=8, description="User password (min 8 characters)"
    )
    name: str = Field(
        ..., min_length=1, max_length=100, description="User display name"
    )
    timezone: Optional[str] = Field(
        None,
        description="Preferred timezone (IANA identifier, e.g. 'America/Los_Angeles')",
    )
    invite_code: Optional[str] = Field(
        default=None,
        min_length=6,
        max_length=128,
        description="Invitation code when registration is restricted",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "email": "alice@example.com",
                "password": "Pass123!",
                "name": "Alice",
                "timezone": "UTC",
                "invite_code": "abcd1234",
            }
        }
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:  # pragma: no cover - defensive guard
            raise ValueError("Invalid timezone identifier") from exc
        return value


class LoginRequest(BaseModel):
    """User login request schema"""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"email": "alice@example.com", "password": "Pass123!"}
        }
    )


class UserResponse(BaseModel):
    """User information response schema"""

    id: UUID = Field(..., description="User ID (UUID)")
    email: str = Field(..., description="User email address")
    name: str = Field(..., description="User display name")
    is_superuser: bool = Field(..., description="Whether user has superuser privileges")
    timezone: str = Field(..., description="Preferred timezone (IANA identifier)")

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "4d0bfd1f-e6e5-459e-886f-7910b0249f56",
                "email": "alice@example.com",
                "name": "Alice",
                "is_superuser": False,
                "timezone": "UTC",
            }
        },
    )


class RegisterResponse(UserResponse):
    """User registration response schema"""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "id": "93f4d5c9-2c3a-4d6b-8a12-2f7b8f5c1a23",
                "email": "alice@example.com",
                "name": "Alice",
                "is_superuser": False,
                "timezone": "UTC",
            }
        },
    )


class LoginResponse(BaseModel):
    """User login response schema"""

    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")
    user: UserResponse = Field(..., description="User information")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 1800,
                "user": {
                    "id": "4d0bfd1f-e6e5-459e-886f-7910b0249f56",
                    "email": "alice@example.com",
                    "name": "Alice",
                    "is_superuser": False,
                    "timezone": "UTC",
                },
            }
        }
    )


class RefreshResponse(LoginResponse):
    """Token refresh response schema."""


class PasswordChangeRequest(BaseModel):
    """Password change request schema"""

    current_password: str = Field(..., description="Existing account password")
    new_password: str = Field(..., min_length=8, description="New password")
    new_password_confirm: Optional[str] = Field(
        default=None,
        description="Optional confirmation that must match the new password",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "current_password": "OldPass!23",
                "new_password": "N3wPass!23",
                "new_password_confirm": "N3wPass!23",
            }
        }
    )

    @field_validator("new_password_confirm")
    @classmethod
    def ensure_confirmation_matches(
        cls, value: Optional[str], info: ValidationInfo
    ) -> Optional[str]:
        new_password = info.data.get("new_password")
        if value is not None and value != new_password:
            raise ValueError("Password confirmation does not match")
        return value


class PasswordChangeResponse(BaseModel):
    """Password change success response"""

    message: str = Field(..., description="Human readable success message")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "Password updated successfully",
            }
        }
    )
