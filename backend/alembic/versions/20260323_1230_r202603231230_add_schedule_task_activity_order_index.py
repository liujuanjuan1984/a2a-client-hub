"""Add activity-order index for a2a_schedule_tasks.

Revision ID: r202603231230
Revises: r202603230430
Create Date: 2026-03-23 12:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r202603231230"  # pragma: allowlist secret
down_revision = "r202603230430"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE INDEX ix_a2a_schedule_tasks_user_enabled_activity
            ON {SCHEMA_NAME}.a2a_schedule_tasks (
                user_id,
                enabled,
                GREATEST(updated_at, COALESCE(last_run_at, updated_at)) DESC
            )
            WHERE deleted_at IS NULL AND delete_requested_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_schedule_tasks_user_enabled_activity",
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
