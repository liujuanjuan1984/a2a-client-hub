"""Add pending status to a2a_schedule_executions

Revision ID: f0d714e35080
Revises: r202603031200
Create Date: 2026-03-11 12:15:02.113820

"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f0d714e35080'
down_revision = 'r202603031200'
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    # Adding pending status is just a string update (since we use VARCHAR, not strict ENUM).
    # We will add an index on (status, scheduled_for) to optimize skip-locked polling for the consumer.
    op.create_index(
        "ix_a2a_schedule_executions_queue_poll",
        "a2a_schedule_executions",
        ["status", "scheduled_for"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "uq_a2a_schedule_executions_active_task",
        "a2a_schedule_executions",
        ["task_id"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_a2a_schedule_executions_active_task",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_a2a_schedule_executions_queue_poll",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
