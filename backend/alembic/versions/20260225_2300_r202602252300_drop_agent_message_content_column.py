"""drop legacy agent_messages.content column

Revision ID: r202602252300
Revises: r202602251400
Create Date: 2026-02-25 23:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision = "r202602252300"
down_revision = "r202602251400"
branch_labels = None
depends_on = None


def _has_column(*, table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = inspector.get_columns(table_name, schema=SCHEMA_NAME)
    return any(column.get("name") == column_name for column in columns)


def upgrade() -> None:
    if _has_column(table_name="agent_messages", column_name="content"):
        op.drop_column("agent_messages", "content", schema=SCHEMA_NAME)


def downgrade() -> None:
    if not _has_column(table_name="agent_messages", column_name="content"):
        op.add_column(
            "agent_messages",
            sa.Column(
                "content",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            schema=SCHEMA_NAME,
        )
