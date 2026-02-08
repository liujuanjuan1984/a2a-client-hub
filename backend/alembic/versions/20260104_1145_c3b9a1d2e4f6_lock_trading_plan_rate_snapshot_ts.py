"""lock trading plan rate snapshot timestamp

Revision ID: c3b9a1d2e4f6
Revises: 9f3c1b2a4d7e
Create Date: 2026-01-04 11:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3b9a1d2e4f6'
down_revision = '9f3c1b2a4d7e'
branch_labels = None
depends_on = None


SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.execute(
        f"UPDATE {SCHEMA}.trading_plans "
        "SET rate_snapshot_ts = created_at "
        "WHERE rate_snapshot_ts IS NULL"
    )
    op.alter_column(
        'trading_plans',
        'rate_snapshot_ts',
        schema=SCHEMA,
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text('now()'),
    )


def downgrade() -> None:
    op.alter_column(
        'trading_plans',
        'rate_snapshot_ts',
        schema=SCHEMA,
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        server_default=None,
    )
