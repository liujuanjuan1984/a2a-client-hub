"""Add user agent availability snapshots for shared and built-in agents.

Revision ID: r202604131500
Revises: r202604082015
Create Date: 2026-04-13 15:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


revision = "r202604131500"
down_revision = "r202604082015"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.create_table(
        "user_agent_availability_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent_source", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.String(length=120), nullable=False),
        sa.Column(
            "health_status",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column(
            "consecutive_health_check_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_successful_health_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("last_health_check_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "agent_source",
            "agent_id",
            name="uq_user_agent_availability_snapshots_user_source_agent",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_agent_availability_snapshots_user_id",
        "user_agent_availability_snapshots",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_agent_availability_snapshots_agent_source",
        "user_agent_availability_snapshots",
        ["agent_source"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_agent_availability_snapshots_agent_id",
        "user_agent_availability_snapshots",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_agent_availability_snapshots_health_status",
        "user_agent_availability_snapshots",
        ["health_status"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_agent_availability_snapshots_health_status",
        table_name="user_agent_availability_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_user_agent_availability_snapshots_agent_id",
        table_name="user_agent_availability_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_user_agent_availability_snapshots_agent_source",
        table_name="user_agent_availability_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_user_agent_availability_snapshots_user_id",
        table_name="user_agent_availability_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_table("user_agent_availability_snapshots", schema=SCHEMA_NAME)
