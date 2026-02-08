"""add cashflow snapshot ts and source currency

Revision ID: 3a1c9f6e8b2d
Revises: 1d2e3f4a5b6c
Create Date: 2026-01-04 17:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3a1c9f6e8b2d"
down_revision = "1d2e3f4a5b6c"
branch_labels = None
depends_on = None


SCHEMA = "common_compass_schema"


def upgrade() -> None:
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "currency_code",
            sa.String(length=16),
            nullable=False,
            server_default="USD",
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "cashflow_snapshots",
        sa.Column("snapshot_ts", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.execute(
        f"UPDATE {SCHEMA}.cashflow_snapshots "
        "SET snapshot_ts = created_at "
        "WHERE snapshot_ts IS NULL"
    )


def downgrade() -> None:
    op.drop_column("cashflow_snapshots", "snapshot_ts", schema=SCHEMA)
    op.drop_column("cashflow_sources", "currency_code", schema=SCHEMA)
