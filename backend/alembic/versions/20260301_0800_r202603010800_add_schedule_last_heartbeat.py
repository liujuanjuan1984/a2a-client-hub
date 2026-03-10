"""add schedule task heartbeat timestamp

Revision ID: r202603010800
Revises: r202602260100
Create Date: 2026-03-01 08:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r202603010800"
down_revision = "r202602260100"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Most recent heartbeat timestamp for the current running execution",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column("a2a_schedule_tasks", "last_heartbeat_at", schema=SCHEMA_NAME)
