"""add trading plan rate snapshot map

Revision ID: 1d2e3f4a5b6c
Revises: 6d8a7c2f1a9b
Create Date: 2026-01-04 15:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '1d2e3f4a5b6c'
down_revision = '6d8a7c2f1a9b'
branch_labels = None
depends_on = None


SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.add_column(
        'trading_plans',
        sa.Column('rate_snapshot_currency', sa.String(length=16), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        'trading_plans',
        sa.Column('rate_snapshot_rates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column('trading_plans', 'rate_snapshot_rates', schema=SCHEMA)
    op.drop_column('trading_plans', 'rate_snapshot_currency', schema=SCHEMA)
