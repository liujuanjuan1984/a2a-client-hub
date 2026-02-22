"""add user shortcuts table

Revision ID: 0f2a8b8f5e11
Revises: 0c7f5d2a8b9c
Create Date: 2026-02-22 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision = "0f2a8b8f5e11"
down_revision = "0c7f5d2a8b9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_shortcuts",
        sa.Column("id", sa.Uuid(), nullable=False, primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_shortcuts_user_id",
        "user_shortcuts",
        ["user_id"],
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_shortcuts_user_sort_order",
        "user_shortcuts",
        ["user_id", "sort_order"],
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_shortcuts_user_sort_order",
        table_name="user_shortcuts",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_user_shortcuts_user_id",
        table_name="user_shortcuts",
        schema=SCHEMA_NAME,
    )
    op.drop_table("user_shortcuts", schema=SCHEMA_NAME)
