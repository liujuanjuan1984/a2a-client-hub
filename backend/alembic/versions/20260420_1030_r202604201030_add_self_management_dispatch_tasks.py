"""Add durable self-management dispatch task table.

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


def upgrade() -> None:
    op.create_table(
        "self_management_dispatch_tasks",
        sa.Column(
            "task_kind",
            sa.String(length=64),
            nullable=False,
            comment="Dispatch task kind for one self-management background request.",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting",
            comment="Lifecycle status for the durable dispatch task.",
        ),
        sa.Column(
            "dedupe_key",
            sa.String(length=255),
            nullable=True,
            comment="Optional idempotency key used to deduplicate durable dispatch tasks.",
        ),
        sa.Column(
            "task_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Serialized durable dispatch payload for one background request.",
        ),
        sa.Column(
            "last_run_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent dispatch run started.",
        ),
        sa.Column(
            "last_run_finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent dispatch run finished.",
        ),
        sa.Column(
            "last_run_error",
            sa.String(length=255),
            nullable=True,
            comment="Most recent durable dispatch error, if any.",
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
            "dedupe_key",
            name="uq_self_management_dispatch_tasks_dedupe_key",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_self_management_dispatch_tasks_status_updated_at",
        "self_management_dispatch_tasks",
        ["status", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_self_management_dispatch_tasks_kind_status",
        "self_management_dispatch_tasks",
        ["task_kind", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_client_hub_schema_self_management_dispatch_tasks_user_id"),
        "self_management_dispatch_tasks",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_a2a_client_hub_schema_self_management_dispatch_tasks_user_id"),
        table_name="self_management_dispatch_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_self_management_dispatch_tasks_kind_status",
        table_name="self_management_dispatch_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_self_management_dispatch_tasks_status_updated_at",
        table_name="self_management_dispatch_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_table("self_management_dispatch_tasks", schema=SCHEMA_NAME)
