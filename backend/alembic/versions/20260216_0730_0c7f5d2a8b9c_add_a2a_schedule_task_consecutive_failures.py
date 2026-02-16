"""add consecutive_failures to schedule task

Revision ID: 0c7f5d2a8b9c
Revises: 945d785bd00d
Create Date: 2026-02-16 07:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision = "0c7f5d2a8b9c"
down_revision = "945d785bd00d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column("a2a_schedule_tasks", "consecutive_failures", schema=SCHEMA_NAME)
