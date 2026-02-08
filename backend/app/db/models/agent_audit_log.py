"""Audit log model for agent-initiated tool executions."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin


class AgentAuditLog(Base, TimestampMixin):
    """Append-only audit log capturing AI agent tool writes."""

    __tablename__ = "agent_audit_log"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    run_id = Column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="Correlates records belonging to the same tool execution",
    )
    trigger_user_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User on whose behalf the agent acted",
    )
    session_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.agent_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Agent session context if available",
    )
    message_id = Column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Agent message that triggered the tool call",
    )
    agent_name = Column(
        String(64),
        nullable=False,
        comment="Agent profile name",
    )
    tool_name = Column(
        String(128),
        nullable=False,
        index=True,
        comment="Executed tool",
    )
    tool_call_id = Column(
        String(128),
        nullable=True,
        comment="Upstream LLM tool_call identifier if provided",
    )
    operation = Column(
        String(128),
        nullable=True,
        index=True,
        comment="Business-level operation descriptor reported by the tool",
    )
    status = Column(
        String(32),
        nullable=False,
        comment="Execution outcome (finished/failed/partial)",
    )
    error = Column(
        Text,
        nullable=True,
        comment="Error message when execution failed",
    )
    duration_ms = Column(
        Integer,
        nullable=True,
        comment="Execution duration reported by the tool",
    )
    target_entities = Column(
        JSONB,
        nullable=True,
        comment="Structured summary of impacted entities/types",
    )
    before_snapshot = Column(
        JSONB,
        nullable=True,
        comment="Redacted snapshot or diff before execution",
    )
    after_snapshot = Column(
        JSONB,
        nullable=True,
        comment="Redacted snapshot or diff after execution",
    )
    extra = Column(
        JSONB,
        nullable=True,
        comment="Additional metadata payload (arguments, tool-specific info)",
    )

    def as_dict(self) -> Dict[str, Any]:
        """Return a serializable dictionary representation."""

        return {
            "id": str(self.id),
            "run_id": str(self.run_id),
            "user_id": str(self.trigger_user_id),
            "agent_name": self.agent_name,
            "tool_name": self.tool_name,
            "status": self.status,
            "operation": self.operation,
            "error": self.error,
            "target_entities": self.target_entities or {},
            "before_snapshot": self.before_snapshot or {},
            "after_snapshot": self.after_snapshot or {},
            "extra": self.extra or {},
            "created_at": self.created_at_iso,
        }


__all__ = ["AgentAuditLog"]
