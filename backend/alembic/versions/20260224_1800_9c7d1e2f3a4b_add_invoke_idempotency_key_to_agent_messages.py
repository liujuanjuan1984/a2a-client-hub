"""add invoke_idempotency_key to agent_messages

Revision ID: 9c7d1e2f3a4b
Revises: 5a1b2c3d4e5f
Create Date: 2026-02-24 18:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "9c7d1e2f3a4b"
down_revision: Union[str, None] = "5a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_messages",
        sa.Column(
            "invoke_idempotency_key",
            sa.String(length=160),
            nullable=True,
            comment="Idempotency key for invoke-generated user/agent message pair.",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.agent_messages
            SET invoke_idempotency_key = NULLIF(BTRIM(metadata ->> 'invoke_idempotency_key'), '')
            WHERE invoke_idempotency_key IS NULL
              AND metadata IS NOT NULL
              AND metadata ? 'invoke_idempotency_key'
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY conversation_id, sender, invoke_idempotency_key
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM {SCHEMA_NAME}.agent_messages
                WHERE invoke_idempotency_key IS NOT NULL
                  AND sender IN ('user', 'agent')
            )
            UPDATE {SCHEMA_NAME}.agent_messages AS target
            SET invoke_idempotency_key = NULL
            FROM ranked
            WHERE target.id = ranked.id
              AND ranked.rn > 1
            """
        )
    )

    op.create_index(
        "uq_agent_messages_conversation_sender_invoke_idempotency_key",
        "agent_messages",
        ["conversation_id", "sender", "invoke_idempotency_key"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text(
            "invoke_idempotency_key IS NOT NULL AND sender IN ('user', 'agent')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_agent_messages_conversation_sender_invoke_idempotency_key",
        table_name="agent_messages",
        schema=SCHEMA_NAME,
    )
    op.drop_column("agent_messages", "invoke_idempotency_key", schema=SCHEMA_NAME)
