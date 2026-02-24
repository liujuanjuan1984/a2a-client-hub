"""add conversation_policy

Revision ID: 5a1b2c3d4e5f
Revises: 4f8c9d2e7a11
Create Date: 2026-02-23 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "5a1b2c3d4e5f"
down_revision: Union[str, None] = "4f8c9d2e7a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "conversation_policy",
            sa.String(length=32),
            nullable=False,
            server_default="new_each_run",
            comment="Session policy: new_each_run / reuse_single",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column("a2a_schedule_tasks", "conversation_policy", schema=SCHEMA_NAME)
