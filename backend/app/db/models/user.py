"""
User SQLAlchemy model

This model represents users in the Common Compass system.
Supports multi-user mode with JWT authentication.
"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.models.base import SCHEMA_NAME, Base, SoftDeleteMixin, TimestampMixin
from app.utils.timezone_util import utc_now


class User(Base, TimestampMixin, SoftDeleteMixin):
    """
    User model representing system users

    This model supports multi-user mode with JWT authentication.
    Users must register/login to access the system.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA_NAME}

    # Primary key comes from TimestampMixin as UUID v4

    # User identification
    email = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="User email address (unique)",
    )
    name = Column(String(100), nullable=False, comment="User display name")
    password_hash = Column(
        String(255), nullable=False, comment="Hashed password using bcrypt"
    )

    # User permissions
    is_superuser = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether user has superuser privileges",
    )

    # Account status
    disabled_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Account disabled timestamp (NULL means active)",
    )
    failed_login_attempts = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Consecutive failed login attempts since last success",
    )
    locked_until = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Account temporarily locked until this timestamp",
    )
    last_login_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the most recent successful login",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', name='{self.name}')>"

    @property
    def is_active(self) -> bool:
        """Check if the user account is active (not disabled)"""
        return self.disabled_at is None

    def disable(self) -> None:
        """Disable the user account"""

        self.disabled_at = func.now()

    def enable(self) -> None:
        """Enable the user account"""
        self.disabled_at = None

    def is_locked(self, now: datetime | None = None) -> bool:
        """Check whether the user is temporarily locked due to failed logins."""

        if self.locked_until is None:
            return False
        reference = now or utc_now()
        return self.locked_until > reference

    def reset_login_state(self) -> None:
        """Clear accumulated failed login counters and lock state."""

        self.failed_login_attempts = 0
        self.locked_until = None
