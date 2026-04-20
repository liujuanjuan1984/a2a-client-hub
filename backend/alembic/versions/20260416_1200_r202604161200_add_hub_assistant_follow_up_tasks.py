"""Add durable Hub Assistant follow-up task table.

Revision ID: r202604161200
Revises: r202604131730
Create Date: 2026-04-16 12:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "r202604161200"
down_revision = "r202604131730"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.create_table(
        "hub_assistant_follow_up_tasks",
        sa.Column(
            "hub_assistant_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_NAME}.conversation_threads.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            comment="Hub Assistant conversation that owns this follow-up substrate.",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting",
            comment="Lifecycle status for the durable follow-up substrate.",
        ),
        sa.Column(
            "tracked_conversation_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Current target conversation ids tracked by the Hub Assistant.",
        ),
        sa.Column(
            "target_agent_message_anchors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Latest observed target-agent text message id per tracked conversation.",
        ),
        sa.Column(
            "last_run_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent follow-up run started.",
        ),
        sa.Column(
            "last_run_finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent follow-up run finished.",
        ),
        sa.Column(
            "last_run_error",
            sa.String(length=255),
            nullable=True,
            comment="Most recent background follow-up execution error, if any.",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            comment="Primary key (UUID v4)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Record last update timestamp",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.UniqueConstraint(
            "user_id",
            "hub_assistant_conversation_id",
            name="uq_hub_assistant_follow_up_tasks_user_conversation",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_hub_assistant_follow_up_tasks_status_updated_at",
        "hub_assistant_follow_up_tasks",
        ["status", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_hub_assistant_follow_up_tasks_conversation_status",
        "hub_assistant_follow_up_tasks",
        ["hub_assistant_conversation_id", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_client_hub_schema_hub_assistant_follow_up_tasks_hub_assistant_conversation_id"),
        "hub_assistant_follow_up_tasks",
        ["hub_assistant_conversation_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_client_hub_schema_hub_assistant_follow_up_tasks_user_id"),
        "hub_assistant_follow_up_tasks",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_a2a_client_hub_schema_hub_assistant_follow_up_tasks_user_id"),
        table_name="hub_assistant_follow_up_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_a2a_client_hub_schema_hub_assistant_follow_up_tasks_hub_assistant_conversation_id"),
        table_name="hub_assistant_follow_up_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_hub_assistant_follow_up_tasks_conversation_status",
        table_name="hub_assistant_follow_up_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_hub_assistant_follow_up_tasks_status_updated_at",
        table_name="hub_assistant_follow_up_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_table("hub_assistant_follow_up_tasks", schema=SCHEMA_NAME)
