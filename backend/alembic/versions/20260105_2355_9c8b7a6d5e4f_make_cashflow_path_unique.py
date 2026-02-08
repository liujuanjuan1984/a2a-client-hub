"""make cashflow path unique per tree

Revision ID: 9c8b7a6d5e4f
Revises: 4f1b2c3d4e5f
Create Date: 2026-01-05 23:55:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "9c8b7a6d5e4f"
down_revision = "4f1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    duplicates = conn.execute(
        sa.text(
            f"""
            SELECT user_id, tree_id, path, COUNT(*) AS cnt
            FROM {SCHEMA_NAME}.cashflow_sources
            WHERE deleted_at IS NULL
            GROUP BY user_id, tree_id, path
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).fetchone()
    if duplicates:
        raise RuntimeError(
            "Detected duplicate cashflow source paths; resolve duplicates before "
            "applying unique constraint."
        )

    op.drop_index(
        "ix_cashflow_sources_user_tree_path",
        table_name="cashflow_sources",
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_cashflow_sources_user_tree_path",
        "cashflow_sources",
        ["user_id", "tree_id", "path"],
        unique=True,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_cashflow_sources_user_tree_path",
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
