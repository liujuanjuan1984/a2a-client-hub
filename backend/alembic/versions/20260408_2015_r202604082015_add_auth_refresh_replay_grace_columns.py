"""add auth refresh replay grace columns

Revision ID: r202604082015
Revises: r202604081200
Create Date: 2026-04-08 20:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME

# revision identifiers, used by Alembic.
revision = "r202604082015"
down_revision = "r202604081200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_refresh_sessions",
        sa.Column(
            "previous_jti",
            sa.String(length=64),
            nullable=True,
            comment="Immediately previous refresh JWT jti tolerated during rotation races.",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "auth_refresh_sessions",
        sa.Column(
            "previous_jti_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Expiry timestamp for short replay grace on the previous refresh JWT jti.",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column(
        "auth_refresh_sessions",
        "previous_jti_expires_at",
        schema=SCHEMA_NAME,
    )
    op.drop_column(
        "auth_refresh_sessions",
        "previous_jti",
        schema=SCHEMA_NAME,
    )
