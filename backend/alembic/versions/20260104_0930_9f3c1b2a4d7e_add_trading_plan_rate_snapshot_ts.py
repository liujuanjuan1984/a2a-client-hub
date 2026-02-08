"""add trading plan rate snapshot timestamp

Revision ID: 9f3c1b2a4d7e
Revises: 7e2b3147811a
Create Date: 2026-01-04 09:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3c1b2a4d7e'
down_revision = '7e2b3147811a'
branch_labels = None
depends_on = None


SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.add_column(
        'trading_plans',
        sa.Column('rate_snapshot_ts', sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.trading_plans "
        "SET rate_snapshot_ts = created_at "
        "WHERE rate_snapshot_ts IS NULL"
    )


def downgrade() -> None:
    op.drop_column('trading_plans', 'rate_snapshot_ts', schema=SCHEMA)
