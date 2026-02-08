"""add cashflow exchange rates map

Revision ID: 6d8a7c2f1a9b
Revises: c3b9a1d2e4f6
Create Date: 2026-01-04 12:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '6d8a7c2f1a9b'
down_revision = 'c3b9a1d2e4f6'
branch_labels = None
depends_on = None


SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.add_column(
        'cashflow_snapshots',
        sa.Column('exchange_rates', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column('cashflow_snapshots', 'exchange_rates', schema=SCHEMA)
