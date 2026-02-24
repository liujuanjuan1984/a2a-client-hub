"""add timezone to schedule tasks

Revision ID: r202602241930
Revises: r202602241900
Create Date: 2026-02-24 19:30:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "r202602241930"
down_revision: Union[str, None] = "r202602241900"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_tasks",
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
            comment="IANA timezone representing user scheduling intent",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column("a2a_schedule_tasks", "timezone", schema=SCHEMA_NAME)
