"""reset unified schema baseline v4

Revision ID: r202602251400
Revises:
Create Date: 2026-02-25 14:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models import *  # noqa: F401,F403
from app.db.models.base import Base, SCHEMA_NAME


# revision identifiers, used by Alembic.
revision = "r202602251400"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}"))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
