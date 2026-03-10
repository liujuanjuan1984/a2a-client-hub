"""add deferred delete marker and running-state consistency constraints

Revision ID: r202603031200
Revises: r202603010800
Create Date: 2026-03-03 12:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r202603031200"
down_revision = "r202603010800"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "delete_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when user requested deletion while run is still in progress",
        ),
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_a2a_schedule_tasks_running_global",
        "a2a_schedule_tasks",
        ["last_run_status", "current_run_id", "deleted_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_schedule_tasks_running_agent",
        "a2a_schedule_tasks",
        ["agent_id", "last_run_status", "current_run_id", "deleted_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.create_check_constraint(
        "ck_a2a_schedule_tasks_running_requires_fields",
        "a2a_schedule_tasks",
        "(last_run_status <> 'running') OR "
        "(current_run_id IS NOT NULL AND running_started_at IS NOT NULL)",
        schema=SCHEMA_NAME,
    )
    op.create_check_constraint(
        "ck_a2a_schedule_tasks_current_run_requires_running",
        "a2a_schedule_tasks",
        "(current_run_id IS NULL) OR (last_run_status = 'running')",
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_a2a_schedule_tasks_current_run_requires_running",
        "a2a_schedule_tasks",
        type_="check",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "ck_a2a_schedule_tasks_running_requires_fields",
        "a2a_schedule_tasks",
        type_="check",
        schema=SCHEMA_NAME,
    )

    op.drop_index(
        "ix_a2a_schedule_tasks_running_agent",
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_a2a_schedule_tasks_running_global",
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )

    op.drop_column("a2a_schedule_tasks", "delete_requested_at", schema=SCHEMA_NAME)
