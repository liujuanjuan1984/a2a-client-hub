"""add schedule run_id state machine fields

Revision ID: 4f8c9d2e7a11
Revises: 1a2b3c4d5e6f
Create Date: 2026-02-23 11:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "4f8c9d2e7a11"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "current_run_id",
            postgresql.UUID(as_uuid=True),
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
        "a2a_schedule_executions",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="Unique identifier for one execution run lifecycle",
        ),
        schema=SCHEMA_NAME,
    )
    op.execute(
        sa.text(
            f"UPDATE {SCHEMA_NAME}.a2a_schedule_executions "
            "SET run_id = id WHERE run_id IS NULL"
        )
    )
    op.alter_column(
        "a2a_schedule_executions",
        "run_id",
        schema=SCHEMA_NAME,
        nullable=False,
    )
    op.create_index(
        "ix_a2a_schedule_executions_run_id",
        "a2a_schedule_executions",
        ["run_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        "uq_a2a_schedule_executions_task_run",
        "a2a_schedule_executions",
        ["task_id", "run_id"],
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_a2a_schedule_executions_task_run",
        "a2a_schedule_executions",
        schema=SCHEMA_NAME,
        type_="unique",
    )
    op.drop_index(
        "ix_a2a_schedule_executions_run_id",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_schedule_executions", "run_id", schema=SCHEMA_NAME)

    op.drop_column("a2a_schedule_tasks", "running_started_at", schema=SCHEMA_NAME)
    op.drop_column("a2a_schedule_tasks", "current_run_id", schema=SCHEMA_NAME)
