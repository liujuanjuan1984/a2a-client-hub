"""add cashflow billing cycle support

Revision ID: b1a2c3d4e5f6
Revises: 6838112514e9
Create Date: 2025-11-03 10:15:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b1a2c3d4e5f6"
down_revision = "6838112514e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "kind",
            sa.String(length=16),
            nullable=False,
            server_default="regular",
        ),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_cycle_type", sa.String(length=16), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_cycle_interval", sa.Integer(), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_anchor_day", sa.Integer(), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_anchor_date", sa.Date(), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_post_to", sa.String(length=8), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "billing_default_amount",
            sa.Numeric(precision=20, scale=8),
            nullable=True,
        ),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("billing_default_note", sa.Text(), nullable=True),
        schema='common_compass_schema',
    )
    op.add_column(
        "cashflow_sources",
        sa.Column(
            "billing_requires_manual_input",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema='common_compass_schema',
    )
    op.create_index(
        "ix_cashflow_sources_user_kind",
        "cashflow_sources",
        ["user_id", "kind"],
        unique=False,
        schema='common_compass_schema',
    )
    op.create_table(
        "cashflow_billing_entries",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("cycle_start", sa.Date(), nullable=False),
        sa.Column("cycle_end", sa.Date(), nullable=False),
        sa.Column(
            "posted_month",
            sa.Date(),
            nullable=False,
            comment="First day of natural month",
        ),
        sa.Column("amount", sa.Numeric(precision=20, scale=8), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "auto_generated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            comment="Primary key (UUID v4)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Record last update timestamp",
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{'common_compass_schema'}.cashflow_sources.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{'common_compass_schema'}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_id",
            "cycle_start",
            "cycle_end",
            name="uq_cashflow_billing_cycle",
        ),
        schema='common_compass_schema',
    )
    op.create_index(
        "ix_cashflow_billing_entries_source_month",
        "cashflow_billing_entries",
        ["source_id", "posted_month"],
        unique=False,
        schema='common_compass_schema',
    )
    op.create_index(op.f('ix_common_compass_schema_cashflow_billing_entries_user_id'), 'cashflow_billing_entries', ['user_id'], unique=False, schema='common_compass_schema')

    # Ensure existing sources remain regular to avoid misclassification
    op.execute(
        sa.text(
            f"""
            UPDATE {'common_compass_schema'}.cashflow_sources
            SET kind = 'regular',
                billing_cycle_type = NULL,
                billing_cycle_interval = NULL,
                billing_anchor_day = NULL,
                billing_anchor_date = NULL,
                billing_post_to = NULL,
                billing_default_amount = NULL,
                billing_default_note = NULL,
                billing_requires_manual_input = FALSE
            WHERE kind IS NULL
            """
        )
    )

    op.alter_column(
        "cashflow_sources",
        "kind",
        server_default=None,
        schema='common_compass_schema',
    )
    op.alter_column(
        "cashflow_sources",
        "billing_requires_manual_input",
        server_default=None,
        schema='common_compass_schema',
    )


def downgrade() -> None:
    op.alter_column(
        "cashflow_sources",
        "billing_requires_manual_input",
        server_default=sa.text("false"),
        schema='common_compass_schema',
    )
    op.alter_column(
        "cashflow_sources",
        "kind",
        server_default=sa.text("'regular'"),
        schema='common_compass_schema',
    )
    op.drop_index(
        "ix_cashflow_billing_entries_source_month",
        table_name="cashflow_billing_entries",
        schema='common_compass_schema',
    )
    op.drop_table("cashflow_billing_entries", schema='common_compass_schema')
    op.drop_index(
        "ix_cashflow_sources_user_kind",
        table_name="cashflow_sources",
        schema='common_compass_schema',
    )
    op.drop_index(op.f('ix_common_compass_schema_cashflow_billing_entries_user_id'), table_name='cashflow_billing_entries', schema='common_compass_schema')
    op.drop_column(
        "cashflow_sources",
        "billing_requires_manual_input",
        schema='common_compass_schema',
    )
    op.drop_column("cashflow_sources", "billing_default_note", schema='common_compass_schema')
    op.drop_column(
        "cashflow_sources",
        "billing_default_amount",
        schema='common_compass_schema',
    )
    op.drop_column("cashflow_sources", "billing_post_to", schema='common_compass_schema')
    op.drop_column("cashflow_sources", "billing_anchor_date", schema='common_compass_schema')
    op.drop_column("cashflow_sources", "billing_anchor_day", schema='common_compass_schema')
    op.drop_column(
        "cashflow_sources",
        "billing_cycle_interval",
        schema='common_compass_schema',
    )
    op.drop_column("cashflow_sources", "billing_cycle_type", schema='common_compass_schema')
    op.drop_column("cashflow_sources", "kind", schema='common_compass_schema')
