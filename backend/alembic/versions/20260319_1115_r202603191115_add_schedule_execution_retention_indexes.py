"""Add retention-oriented indexes for a2a_schedule_executions.

Revision ID: r202603191115
Revises: r202603181130
Create Date: 2026-03-19 11:15:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r202603191115"
down_revision = "r202603181130"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.create_index(
        "ix_a2a_schedule_executions_user_task_started",
        "a2a_schedule_executions",
        ["user_id", "task_id", "started_at", "id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_schedule_executions_terminal_finished",
        "a2a_schedule_executions",
        ["finished_at"],
        unique=False,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("status IN ('success', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_schedule_executions_terminal_finished",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_a2a_schedule_executions_user_task_started",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
