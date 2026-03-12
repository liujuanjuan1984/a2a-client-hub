"""Shift schedule running truth to executions and drop task run-state columns.

Revision ID: 4b6c6e0d8a2f
Revises: f0d714e35080
Create Date: 2026-03-12 14:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "4b6c6e0d8a2f"  # pragma: allowlist secret
down_revision = "f0d714e35080"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def _legacy_running_projection_count() -> int:
    bind = op.get_bind()
    return int(
        bind.execute(
            sa.text(
                f"""
                SELECT count(*)
                FROM {SCHEMA_NAME}.a2a_schedule_tasks
                WHERE current_run_id IS NOT NULL
                   OR running_started_at IS NOT NULL
                   OR last_heartbeat_at IS NOT NULL
                   OR last_run_status = 'running'
                """
            )
        ).scalar_one()
    )


def upgrade() -> None:
    if _legacy_running_projection_count() > 0:
        raise RuntimeError(
            "Legacy schedule task running-state columns are still populated. "
            "Run `uv run python scripts/backfill_schedule_execution_running_truth.py "
            "--apply` before applying revision 4b6c6e0d8a2f."
        )

    op.add_column(
        "a2a_schedule_executions",
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Most recent heartbeat observed while execution is running",
        ),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "a2a_schedule_executions",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "a2a_schedule_executions",
        "status",
        existing_type=sa.String(length=32),
        server_default=None,
        schema=SCHEMA_NAME,
    )

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
    op.drop_column("a2a_schedule_tasks", "last_heartbeat_at", schema=SCHEMA_NAME)
    op.drop_column("a2a_schedule_tasks", "running_started_at", schema=SCHEMA_NAME)
    op.drop_column("a2a_schedule_tasks", "current_run_id", schema=SCHEMA_NAME)


def downgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "current_run_id",
            sa.UUID(),
            nullable=True,
            comment="Identifier of the currently running execution attempt",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "running_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when the current running execution was claimed",
        ),
        schema=SCHEMA_NAME,
    )
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

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.a2a_schedule_executions
            SET started_at = scheduled_for
            WHERE started_at IS NULL
            """
        )
    )
    op.alter_column(
        "a2a_schedule_executions",
        "status",
        existing_type=sa.String(length=32),
        server_default="running",
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "a2a_schedule_executions",
        "started_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_schedule_executions", "last_heartbeat_at", schema=SCHEMA_NAME)
