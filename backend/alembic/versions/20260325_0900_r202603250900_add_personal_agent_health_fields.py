"""Add health check fields to a2a_agents.

Revision ID: r202603250900
Revises: r202603231230
Create Date: 2026-03-25 09:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r202603250900"  # pragma: allowlist secret
down_revision = "r202603231230"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "a2a_agents",
        sa.Column(
            "health_status",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
            comment="Latest persisted health check status.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "a2a_agents",
        sa.Column(
            "consecutive_health_check_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Consecutive failed health checks.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "a2a_agents",
        sa.Column(
            "last_health_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the latest health check attempt.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "a2a_agents",
        sa.Column(
            "last_successful_health_check_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp of the latest successful health check attempt.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "a2a_agents",
        sa.Column(
            "last_health_check_error",
            sa.Text(),
            nullable=True,
            comment="Latest persisted health check error summary.",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_agents_health_status",
        "a2a_agents",
        ["health_status"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_agents_health_status",
        table_name="a2a_agents",
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_agents", "last_health_check_error", schema=SCHEMA_NAME)
    op.drop_column(
        "a2a_agents",
        "last_successful_health_check_at",
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_agents", "last_health_check_at", schema=SCHEMA_NAME)
    op.drop_column(
        "a2a_agents",
        "consecutive_health_check_failures",
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_agents", "health_status", schema=SCHEMA_NAME)
