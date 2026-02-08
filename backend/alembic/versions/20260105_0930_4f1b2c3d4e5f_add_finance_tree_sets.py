"""add finance account/cashflow tree sets

Revision ID: 4f1b2c3d4e5f
Revises: 3a1c9f6e8b2d
Create Date: 2026-01-05 09:30:00.000000

"""

from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "4f1b2c3d4e5f"
down_revision = "3a1c9f6e8b2d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "finance_account_trees",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key (UUID v4)"),
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
        sa.Column("user_id", sa.UUID(), nullable=False, comment="Data owner (UUID)"),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete timestamp (NULL means not deleted)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA_NAME}.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "name", name="uq_finance_account_tree_user_name"
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_finance_account_trees_id"),
        "finance_account_trees",
        ["id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_finance_account_trees_user_id"),
        "finance_account_trees",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_finance_account_trees_user_default",
        "finance_account_trees",
        ["user_id", "is_default"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "cashflow_source_trees",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key (UUID v4)"),
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
        sa.Column("user_id", sa.UUID(), nullable=False, comment="Data owner (UUID)"),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete timestamp (NULL means not deleted)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], [f"{SCHEMA_NAME}.users.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "name", name="uq_cashflow_source_tree_user_name"
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_cashflow_source_trees_id"),
        "cashflow_source_trees",
        ["id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_cashflow_source_trees_user_id"),
        "cashflow_source_trees",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_source_trees_user_default",
        "cashflow_source_trees",
        ["user_id", "is_default"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.add_column(
        "finance_accounts",
        sa.Column("tree_id", sa.UUID(), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "finance_snapshots",
        sa.Column("tree_id", sa.UUID(), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_sources",
        sa.Column("tree_id", sa.UUID(), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.add_column(
        "cashflow_snapshots",
        sa.Column("tree_id", sa.UUID(), nullable=True),
        schema=SCHEMA_NAME,
    )

    conn = op.get_bind()
    user_rows = conn.execute(
        sa.text(f"SELECT id FROM {SCHEMA_NAME}.users")
    ).fetchall()

    account_tree_map = {}
    cashflow_tree_map = {}
    for row in user_rows:
        user_id = row[0]
        account_tree_id = uuid4()
        cashflow_tree_id = uuid4()
        account_tree_map[user_id] = account_tree_id
        cashflow_tree_map[user_id] = cashflow_tree_id
        conn.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA_NAME}.finance_account_trees
                    (id, user_id, name, is_default, created_at, updated_at)
                VALUES
                    (:id, :user_id, :name, TRUE, now(), now())
                """
            ),
            {"id": account_tree_id, "user_id": user_id, "name": "Default"},
        )
        conn.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA_NAME}.cashflow_source_trees
                    (id, user_id, name, is_default, created_at, updated_at)
                VALUES
                    (:id, :user_id, :name, TRUE, now(), now())
                """
            ),
            {"id": cashflow_tree_id, "user_id": user_id, "name": "Default"},
        )

    for user_id, tree_id in account_tree_map.items():
        conn.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA_NAME}.finance_accounts
                SET tree_id = :tree_id
                WHERE user_id = :user_id
                """
            ),
            {"tree_id": tree_id, "user_id": user_id},
        )
        conn.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA_NAME}.finance_snapshots
                SET tree_id = :tree_id
                WHERE user_id = :user_id
                """
            ),
            {"tree_id": tree_id, "user_id": user_id},
        )

    for user_id, tree_id in cashflow_tree_map.items():
        conn.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA_NAME}.cashflow_sources
                SET tree_id = :tree_id
                WHERE user_id = :user_id
                """
            ),
            {"tree_id": tree_id, "user_id": user_id},
        )
        conn.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA_NAME}.cashflow_snapshots
                SET tree_id = :tree_id
                WHERE user_id = :user_id
                """
            ),
            {"tree_id": tree_id, "user_id": user_id},
        )

    op.alter_column(
        "finance_accounts",
        "tree_id",
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "finance_snapshots",
        "tree_id",
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_sources",
        "tree_id",
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_snapshots",
        "tree_id",
        nullable=False,
        schema=SCHEMA_NAME,
    )

    op.create_foreign_key(
        "fk_finance_accounts_tree_id",
        "finance_accounts",
        "finance_account_trees",
        ["tree_id"],
        ["id"],
        source_schema=SCHEMA_NAME,
        referent_schema=SCHEMA_NAME,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_finance_snapshots_tree_id",
        "finance_snapshots",
        "finance_account_trees",
        ["tree_id"],
        ["id"],
        source_schema=SCHEMA_NAME,
        referent_schema=SCHEMA_NAME,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_cashflow_sources_tree_id",
        "cashflow_sources",
        "cashflow_source_trees",
        ["tree_id"],
        ["id"],
        source_schema=SCHEMA_NAME,
        referent_schema=SCHEMA_NAME,
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_cashflow_snapshots_tree_id",
        "cashflow_snapshots",
        "cashflow_source_trees",
        ["tree_id"],
        ["id"],
        source_schema=SCHEMA_NAME,
        referent_schema=SCHEMA_NAME,
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "uq_finance_account_parent_name",
        "finance_accounts",
        type_="unique",
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        "uq_finance_account_tree_parent_name",
        "finance_accounts",
        ["user_id", "tree_id", "parent_id", "name"],
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_finance_accounts_user_path",
        table_name="finance_accounts",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_finance_accounts_user_tree_path",
        "finance_accounts",
        ["user_id", "tree_id", "path"],
        unique=True,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_finance_accounts_tree_id",
        "finance_accounts",
        ["tree_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.drop_index(
        "ix_finance_snapshots_user_ts",
        table_name="finance_snapshots",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_finance_snapshots_user_tree_ts",
        "finance_snapshots",
        ["user_id", "tree_id", "snapshot_ts"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_finance_snapshots_tree_id",
        "finance_snapshots",
        ["tree_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.drop_constraint(
        "uq_cashflow_source_parent_name",
        "cashflow_sources",
        type_="unique",
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        "uq_cashflow_source_tree_parent_name",
        "cashflow_sources",
        ["user_id", "tree_id", "parent_id", "name"],
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_sources_user_path",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_sources_user_tree_path",
        "cashflow_sources",
        ["user_id", "tree_id", "path"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_sources_user_kind",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_sources_user_tree_kind",
        "cashflow_sources",
        ["user_id", "tree_id", "kind"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_sources_tree_id",
        "cashflow_sources",
        ["tree_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.drop_index(
        "ix_cashflow_snapshots_user_period",
        table_name="cashflow_snapshots",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_snapshots_user_tree_period",
        "cashflow_snapshots",
        ["user_id", "tree_id", "period_start", "period_end"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_snapshots_tree_id",
        "cashflow_snapshots",
        ["tree_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.alter_column(
        "finance_account_trees",
        "is_default",
        server_default=None,
        existing_type=sa.Boolean(),
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        "cashflow_source_trees",
        "is_default",
        server_default=None,
        existing_type=sa.Boolean(),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.create_index(
        "ix_cashflow_snapshots_user_period",
        "cashflow_snapshots",
        ["user_id", "period_start", "period_end"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_snapshots_user_tree_period",
        table_name="cashflow_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_snapshots_tree_id",
        table_name="cashflow_snapshots",
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_cashflow_sources_user_kind",
        "cashflow_sources",
        ["user_id", "kind"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_sources_user_tree_kind",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_sources_user_path",
        "cashflow_sources",
        ["user_id", "path"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_sources_user_tree_path",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_cashflow_sources_tree_id",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "uq_cashflow_source_tree_parent_name",
        "cashflow_sources",
        type_="unique",
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        "uq_cashflow_source_parent_name",
        "cashflow_sources",
        ["user_id", "parent_id", "name"],
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_finance_snapshots_user_ts",
        "finance_snapshots",
        ["user_id", "snapshot_ts"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_finance_snapshots_user_tree_ts",
        table_name="finance_snapshots",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_finance_snapshots_tree_id",
        table_name="finance_snapshots",
        schema=SCHEMA_NAME,
    )

    op.create_index(
        "ix_finance_accounts_user_path",
        "finance_accounts",
        ["user_id", "path"],
        unique=True,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_finance_accounts_user_tree_path",
        table_name="finance_accounts",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_finance_accounts_tree_id",
        table_name="finance_accounts",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "uq_finance_account_tree_parent_name",
        "finance_accounts",
        type_="unique",
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        "uq_finance_account_parent_name",
        "finance_accounts",
        ["user_id", "parent_id", "name"],
        schema=SCHEMA_NAME,
    )

    op.drop_constraint(
        "fk_cashflow_snapshots_tree_id",
        "cashflow_snapshots",
        type_="foreignkey",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "fk_cashflow_sources_tree_id",
        "cashflow_sources",
        type_="foreignkey",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "fk_finance_snapshots_tree_id",
        "finance_snapshots",
        type_="foreignkey",
        schema=SCHEMA_NAME,
    )
    op.drop_constraint(
        "fk_finance_accounts_tree_id",
        "finance_accounts",
        type_="foreignkey",
        schema=SCHEMA_NAME,
    )

    op.drop_column("cashflow_snapshots", "tree_id", schema=SCHEMA_NAME)
    op.drop_column("cashflow_sources", "tree_id", schema=SCHEMA_NAME)
    op.drop_column("finance_snapshots", "tree_id", schema=SCHEMA_NAME)
    op.drop_column("finance_accounts", "tree_id", schema=SCHEMA_NAME)

    op.drop_index(
        "ix_cashflow_source_trees_user_default",
        table_name="cashflow_source_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_cashflow_source_trees_user_id"),
        table_name="cashflow_source_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_cashflow_source_trees_id"),
        table_name="cashflow_source_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_table("cashflow_source_trees", schema=SCHEMA_NAME)

    op.drop_index(
        "ix_finance_account_trees_user_default",
        table_name="finance_account_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_finance_account_trees_user_id"),
        table_name="finance_account_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_finance_account_trees_id"),
        table_name="finance_account_trees",
        schema=SCHEMA_NAME,
    )
    op.drop_table("finance_account_trees", schema=SCHEMA_NAME)
