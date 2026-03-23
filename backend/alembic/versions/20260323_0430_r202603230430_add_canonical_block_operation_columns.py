"""Add canonical block operation columns to agent_message_blocks.

Revision ID: r202603230430
Revises: r202603191115
Create Date: 2026-03-23 04:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r202603230430"  # pragma: allowlist secret
down_revision = "r202603191115"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "agent_message_blocks",
        sa.Column(
            "block_id",
            sa.String(length=128),
            nullable=True,
            comment="Stable logical block id used by append/replace/finalize operations.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "agent_message_blocks",
        sa.Column(
            "lane_id",
            sa.String(length=64),
            nullable=True,
            comment="Stable render lane id for this logical block.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "agent_message_blocks",
        sa.Column(
            "base_seq",
            sa.Integer(),
            nullable=True,
            comment="Latest authoritative base sequence accepted for this block.",
        ),
        schema=SCHEMA_NAME,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.agent_message_blocks
            SET lane_id = CASE
                WHEN block_type = 'text' THEN 'primary_text'
                WHEN block_type IS NULL OR block_type = '' THEN 'text'
                ELSE block_type
            END
            WHERE lane_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.agent_message_blocks
            SET block_id = message_id::text || ':' || lane_id || ':' || block_seq::text
            WHERE block_id IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.agent_message_blocks
            SET base_seq = COALESCE(end_event_seq, start_event_seq, block_seq)
            WHERE base_seq IS NULL
            """
        )
    )
    op.alter_column(
        "agent_message_blocks",
        "block_id",
        schema=SCHEMA_NAME,
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.alter_column(
        "agent_message_blocks",
        "lane_id",
        schema=SCHEMA_NAME,
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_index(
        "ix_agent_message_blocks_message_id_block_id",
        "agent_message_blocks",
        ["message_id", "block_id"],
        unique=True,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_message_blocks_message_id_block_id",
        table_name="agent_message_blocks",
        schema=SCHEMA_NAME,
    )
    op.drop_column("agent_message_blocks", "base_seq", schema=SCHEMA_NAME)
    op.drop_column("agent_message_blocks", "lane_id", schema=SCHEMA_NAME)
    op.drop_column("agent_message_blocks", "block_id", schema=SCHEMA_NAME)
