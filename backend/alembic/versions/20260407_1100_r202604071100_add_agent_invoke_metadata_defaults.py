"""add agent invoke metadata defaults

Revision ID: r202604071100
Revises: r202603261200
Create Date: 2026-04-07 11:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME

# revision identifiers, used by Alembic.
revision = "r202604071100"
down_revision = "r202603261200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "a2a_agents",
        sa.Column(
            "invoke_metadata_defaults",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Agent-level default invoke metadata merged during outbound invoke",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column(
        "a2a_agents",
        "invoke_metadata_defaults",
        schema=SCHEMA_NAME,
    )
