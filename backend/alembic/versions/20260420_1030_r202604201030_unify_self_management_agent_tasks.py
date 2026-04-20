"""Unify built-in self-management durable tasks into one table.

Revision ID: r202604201030
Revises: r202604161200
Create Date: 2026-04-20 10:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "r202604201030"
down_revision = "r202604161200"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")

_FOLLOW_UP_KIND = "follow_up_watch"


def upgrade() -> None:
    op.rename_table(
        "built_in_follow_up_tasks",
        "self_management_agent_tasks",
        schema=SCHEMA_NAME,
    )

    op.drop_constraint(
        "uq_built_in_follow_up_tasks_user_conversation",
        "self_management_agent_tasks",
        schema=SCHEMA_NAME,
        type_="unique",
    )
    op.drop_index(
        op.f("ix_a2a_client_hub_schema_built_in_follow_up_tasks_user_id"),
        table_name="self_management_agent_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_a2a_client_hub_schema_built_in_follow_up_tasks_built_in_conversation_id"),
        table_name="self_management_agent_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_built_in_follow_up_tasks_conversation_status",
        table_name="self_management_agent_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_built_in_follow_up_tasks_status_updated_at",
        table_name="self_management_agent_tasks",
        schema=SCHEMA_NAME,
    )

    op.add_column(
        "self_management_agent_tasks",
        sa.Column(
            "task_kind",
            sa.String(length=64),
            nullable=True,
            comment="Built-in self-management task kind.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "self_management_agent_tasks",
        sa.Column(
            "dedupe_key",
            sa.String(length=255),
            nullable=True,
            comment="Optional idempotency key used to deduplicate tasks.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "self_management_agent_tasks",
        sa.Column(
            "task_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Serialized background task payload.",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.self_management_agent_tasks
            SET task_kind = :task_kind,
                task_payload = jsonb_build_object(
                    'tracked_conversation_ids',
                    COALESCE(tracked_conversation_ids, '[]'::jsonb),
                    'target_agent_message_anchors',
                    COALESCE(target_agent_message_anchors, '{{}}'::jsonb)
                )
            """
        ).bindparams(task_kind=_FOLLOW_UP_KIND)
    )

    op.alter_column(
        "self_management_agent_tasks",
        "task_kind",
        existing_type=sa.String(length=64),
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "self_management_agent_tasks",
        "task_payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.drop_column(
        "self_management_agent_tasks",
        "tracked_conversation_ids",
        schema=SCHEMA_NAME,
    )
    op.drop_column(
        "self_management_agent_tasks",
        "target_agent_message_anchors",
        schema=SCHEMA_NAME,
    )

    op.create_unique_constraint(
        "uq_self_management_agent_tasks_dedupe_key",
        "self_management_agent_tasks",
        ["dedupe_key"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_self_management_agent_tasks_status_updated_at",
        "self_management_agent_tasks",
        ["status", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_self_management_agent_tasks_kind_status",
        "self_management_agent_tasks",
        ["task_kind", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_self_management_agent_tasks_conversation_kind_status",
        "self_management_agent_tasks",
        ["built_in_conversation_id", "task_kind", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "uq_self_management_agent_tasks_follow_up_conversation",
        "self_management_agent_tasks",
        ["user_id", "built_in_conversation_id"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text(f"task_kind = '{_FOLLOW_UP_KIND}'"),
    )


def downgrade() -> None:
    op.create_table(
        "built_in_follow_up_tasks",
        sa.Column(
            "built_in_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_NAME}.conversation_threads.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            comment="Built-in conversation that owns this follow-up substrate.",
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
            comment="Current target conversation ids tracked by the built-in agent.",
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
            "built_in_conversation_id",
            name="uq_built_in_follow_up_tasks_user_conversation",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA_NAME}.built_in_follow_up_tasks (
                id,
                created_at,
                updated_at,
                user_id,
                built_in_conversation_id,
                status,
                tracked_conversation_ids,
                target_agent_message_anchors,
                last_run_started_at,
                last_run_finished_at,
                last_run_error
            )
            SELECT
                id,
                created_at,
                updated_at,
                user_id,
                built_in_conversation_id,
                status,
                COALESCE(task_payload -> 'tracked_conversation_ids', '[]'::jsonb),
                COALESCE(task_payload -> 'target_agent_message_anchors', '{{}}'::jsonb),
                last_run_started_at,
                last_run_finished_at,
                last_run_error
            FROM {SCHEMA_NAME}.self_management_agent_tasks
            WHERE task_kind = :task_kind
            """
        ).bindparams(task_kind=_FOLLOW_UP_KIND)
    )

    op.create_index(
        "ix_built_in_follow_up_tasks_status_updated_at",
        "built_in_follow_up_tasks",
        ["status", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_built_in_follow_up_tasks_conversation_status",
        "built_in_follow_up_tasks",
        ["built_in_conversation_id", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_client_hub_schema_built_in_follow_up_tasks_built_in_conversation_id"),
        "built_in_follow_up_tasks",
        ["built_in_conversation_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_client_hub_schema_built_in_follow_up_tasks_user_id"),
        "built_in_follow_up_tasks",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.drop_table("self_management_agent_tasks", schema=SCHEMA_NAME)
