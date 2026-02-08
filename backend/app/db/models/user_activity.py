"""User activity model for auditing authentication and account events."""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class UserActivity(Base, TimestampMixin):
    """Append-only log of user behaviours such as register/login actions."""

    __tablename__ = "user_activity"
    __table_args__ = {"schema": SCHEMA_NAME}

    user_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated user if available",
    )
    event_type = Column(
        String(64),
        nullable=False,
        index=True,
        comment="Classification of the recorded activity",
    )
    status = Column(
        String(32),
        nullable=False,
        comment="Outcome descriptor (e.g. success/failed/blocked)",
    )
    payload = Column(
        JSONB,
        nullable=True,
        comment="Flexible metadata payload for the event",
    )

    def as_payload(self) -> Dict[str, Any]:
        """Return payload as a mutable dict for convenience."""

        return dict(self.payload or {})

    @staticmethod
    def build_metadata(
        *,
        email: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Helper for constructing standardised metadata payloads."""

        payload: Dict[str, Any] = {}
        if email:
            payload["email"] = email
        if ip:
            payload["ip"] = ip
        if user_agent:
            payload["user_agent"] = user_agent
        if request_id:
            payload["request_id"] = request_id
        if extra:
            payload.update(extra)
        return payload
