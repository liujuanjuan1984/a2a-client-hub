"""add agent_message_chunks and stream header fields

Revision ID: 7b2a1c4d5e6f
Revises: r202602241900
Create Date: 2026-02-25 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "7b2a1c4d5e6f"
down_revision: Union[str, None] = "r202602241900"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_messages",
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="done",
            comment="Message status: streaming/done/error/interrupted.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "agent_messages",
        sa.Column(
            "finish_reason",
            sa.String(length=64),
            nullable=True,
            comment="Finalized finish reason for stream-generated agent messages.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "agent_messages",
        sa.Column(
            "error_code",
            sa.String(length=64),
            nullable=True,
            comment="Normalized error code for failed/incomplete stream.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "agent_messages",
        sa.Column(
            "summary_text",
            sa.Text(),
            nullable=True,
            comment="Short materialized summary for quick list rendering.",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.agent_messages
            SET
                summary_text = CASE
                    WHEN sender = 'agent' THEN content
                    ELSE summary_text
                END,
                status = CASE
                    WHEN sender = 'agent' THEN 'done'
                    ELSE 'done'
                END
            """
        )
    )

    op.create_table(
        "agent_message_chunks",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_NAME}.agent_messages.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "seq",
            sa.Integer(),
            nullable=False,
            comment="Monotonic sequence for a single message stream.",
        ),
        sa.Column(
            "event_id",
            sa.String(length=128),
            nullable=True,
            comment="Optional upstream event identifier for deduplication.",
        ),
        sa.Column(
            "block_type",
            sa.String(length=32),
            nullable=False,
            comment="Block type: text/reasoning/tool_call/system_error.",
        ),
        sa.Column(
            "content",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="Chunk delta payload.",
        ),
        sa.Column(
            "append",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether this chunk appends to current block.",
        ),
        sa.Column(
            "is_finished",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Whether this chunk marks block finished.",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=True,
            comment="Optional source hint (e.g., final_snapshot).",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_agent_message_chunks_message_id_seq",
        "agent_message_chunks",
        ["message_id", "seq"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "uq_agent_message_chunks_message_id_seq",
        "agent_message_chunks",
        ["message_id", "seq"],
        unique=True,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "uq_agent_message_chunks_message_id_event_id",
        "agent_message_chunks",
        ["message_id", "event_id"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_message_chunks_message_id_event_id",
        table_name="agent_message_chunks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "uq_agent_message_chunks_message_id_seq",
        table_name="agent_message_chunks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_agent_message_chunks_message_id_seq",
        table_name="agent_message_chunks",
        schema=SCHEMA_NAME,
    )
    op.drop_table("agent_message_chunks", schema=SCHEMA_NAME)

    op.drop_column("agent_messages", "summary_text", schema=SCHEMA_NAME)
    op.drop_column("agent_messages", "error_code", schema=SCHEMA_NAME)
    op.drop_column("agent_messages", "finish_reason", schema=SCHEMA_NAME)
    op.drop_column("agent_messages", "status", schema=SCHEMA_NAME)
