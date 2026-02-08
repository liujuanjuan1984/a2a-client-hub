"""add_deleted_at_to_finance_snapshots

Revision ID: b8b6306f4dc4
Revises: 52acb08a7b94
Create Date: 2025-10-18 18:47:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8b6306f4dc4'
down_revision = '52acb08a7b94'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add soft delete flag to finance snapshots."""
    op.add_column(
        'finance_snapshots',
        sa.Column(
            'deleted_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Soft delete timestamp (NULL means not deleted)',
        ),
        schema='common_compass_schema',
    )


def downgrade() -> None:
    """Remove soft delete flag from finance snapshots."""
    op.drop_column(
        'finance_snapshots',
        'deleted_at',
        schema='common_compass_schema',
    )
