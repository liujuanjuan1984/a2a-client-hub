"""Add agent_id to shortcut

Revision ID: 1a2b3c4d5e6f
Revises: 0f2a8b8f5e11
Create Date: 2026-02-22 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME

# revision identifiers, used by alembic.
revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, None] = "0f2a8b8f5e11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_shortcuts",
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="If set, shortcut only applies to this specific agent",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_user_shortcuts_agent_id",
        "user_shortcuts",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_foreign_key(
        "fk_user_shortcuts_agent_id",
        "user_shortcuts",
        "a2a_agents",
        ["agent_id"],
        ["id"],
        source_schema=SCHEMA_NAME,
        referent_schema=SCHEMA_NAME,
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_shortcuts_agent_id",
        "user_shortcuts",
        schema=SCHEMA_NAME,
        type_="foreignkey",
    )
    op.drop_index(
        "ix_user_shortcuts_agent_id",
        table_name="user_shortcuts",
        schema=SCHEMA_NAME,
    )
    op.drop_column("user_shortcuts", "agent_id", schema=SCHEMA_NAME)
