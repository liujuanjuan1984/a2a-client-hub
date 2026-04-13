"""Add structured health reason codes for persisted agent snapshots.

Revision ID: r202604131730
Revises: r202604131500
Create Date: 2026-04-13 17:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


revision = "r202604131730"  # pragma: allowlist secret
down_revision = "r202604131500"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "a2a_agents",
        sa.Column(
            "last_health_check_reason_code",
            sa.String(length=64),
            nullable=True,
            comment="Latest persisted structured health check reason code.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "user_agent_availability_snapshots",
        sa.Column(
            "last_health_check_reason_code",
            sa.String(length=64),
            nullable=True,
            comment="Latest persisted structured availability reason code.",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column(
        "user_agent_availability_snapshots",
        "last_health_check_reason_code",
        schema=SCHEMA_NAME,
    )
    op.drop_column(
        "a2a_agents",
        "last_health_check_reason_code",
        schema=SCHEMA_NAME,
    )
