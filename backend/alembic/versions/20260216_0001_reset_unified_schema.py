"""reset schema as unified baseline

Revision ID: 20260216_0001
Revises:
Create Date: 2026-02-16 00:01:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models import *  # noqa: F401,F403
from app.db.models.base import Base, SCHEMA_NAME


# revision identifiers, used by Alembic.
revision = "20260216_0001"
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
