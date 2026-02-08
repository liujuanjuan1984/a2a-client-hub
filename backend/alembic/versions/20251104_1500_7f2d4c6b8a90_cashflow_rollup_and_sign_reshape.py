"""cashflow rollup and sign reshape

Revision ID: 7f2d4c6b8a90
Revises: b1a2c3d4e5f6
Create Date: 2025-11-04 15:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "7f2d4c6b8a90"
down_revision = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "is_rollup",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "children_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_snapshot_entries",
        sa.Column(
            "is_auto_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_snapshots",
        sa.Column(
            "total_positive",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_snapshots",
        sa.Column(
            "total_negative",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_snapshot_entries
            SET amount = CASE
                WHEN type = 'expense' THEN -ABS(amount)
                ELSE ABS(amount)
            END
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_sources
            SET billing_default_amount = CASE
                WHEN type = 'expense' THEN -ABS(billing_default_amount)
                ELSE ABS(billing_default_amount)
            END
            WHERE billing_default_amount IS NOT NULL
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_snapshots
            SET total_positive = total_income,
                total_negative = -total_expense
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            WITH child_counts AS (
                SELECT parent_id, COUNT(*) AS cnt
                FROM {SCHEMA_NAME}.cashflow_sources
                WHERE parent_id IS NOT NULL AND deleted_at IS NULL
                GROUP BY parent_id
            )
            UPDATE {SCHEMA_NAME}.cashflow_sources AS parent
            SET children_count = child_counts.cnt,
                is_rollup = CASE WHEN child_counts.cnt > 0 THEN TRUE ELSE parent.is_rollup END
            FROM child_counts
            WHERE parent.id = child_counts.parent_id
            """
        )
    )

    op.alter_column(
        "cashflow_sources",
        "is_rollup",
        server_default=None,
        existing_type=sa.Boolean(),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_sources",
        "children_count",
        server_default=None,
        existing_type=sa.Integer(),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_snapshot_entries",
        "is_auto_generated",
        server_default=None,
        existing_type=sa.Boolean(),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_snapshots",
        "total_positive",
        server_default=None,
        existing_type=sa.Numeric(20, 8),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_snapshots",
        "total_negative",
        server_default=None,
        existing_type=sa.Numeric(20, 8),
        schema=SCHEMA_NAME,
    )

    op.drop_column("cashflow_sources", "type", schema=SCHEMA_NAME)
    op.drop_column("cashflow_snapshot_entries", "type", schema=SCHEMA_NAME)


def downgrade() -> None:
    op.add_column(
        "cashflow_snapshot_entries",
        sa.Column(
            "type",
            sa.String(length=16),
            nullable=False,
            server_default="income",
        ),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "type",
            sa.String(length=16),
            nullable=False,
            server_default="income",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_snapshot_entries
            SET type = CASE
                WHEN amount < 0 THEN 'expense'
                ELSE 'income'
            END
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_sources AS s
            SET type = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM {SCHEMA_NAME}.cashflow_snapshot_entries e
                    WHERE e.source_id = s.id AND e.type = 'expense'
                ) THEN 'expense'
                ELSE 'income'
            END
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_sources
            SET billing_default_amount = ABS(billing_default_amount)
            WHERE billing_default_amount IS NOT NULL
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_snapshot_entries
            SET amount = ABS(amount)
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.cashflow_snapshots
            SET total_income = total_positive,
                total_expense = -total_negative
            """
        )
    )

    op.alter_column(
        "cashflow_snapshot_entries",
        "type",
        server_default=None,
        existing_type=sa.String(length=16),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_sources",
        "type",
        server_default=None,
        existing_type=sa.String(length=16),
        schema=SCHEMA_NAME,
    )

    op.drop_column("cashflow_snapshot_entries", "is_auto_generated", schema=SCHEMA_NAME)
    op.drop_column("cashflow_sources", "is_rollup", schema=SCHEMA_NAME)
    op.drop_column("cashflow_sources", "children_count", schema=SCHEMA_NAME)
    op.drop_column("cashflow_snapshots", "total_positive", schema=SCHEMA_NAME)
    op.drop_column("cashflow_snapshots", "total_negative", schema=SCHEMA_NAME)
