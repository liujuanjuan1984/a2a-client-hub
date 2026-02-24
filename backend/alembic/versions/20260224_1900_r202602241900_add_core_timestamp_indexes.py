"""add core timestamp composite indexes

Revision ID: r202602241900
Revises: 9c7d1e2f3a4b
Create Date: 2026-02-24 19:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = "r202602241900"
down_revision: Union[str, None] = "9c7d1e2f3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_messages_conversation_id_created_at",
        "agent_messages",
        ["conversation_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_conversation_threads_user_id_updated_at",
        "conversation_threads",
        ["user_id", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_schedule_tasks_user_id_created_at",
        "a2a_schedule_tasks",
        ["user_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_schedule_tasks_user_id_created_at",
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_conversation_threads_user_id_updated_at",
        table_name="conversation_threads",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_agent_messages_conversation_id_created_at",
        table_name="agent_messages",
        schema=SCHEMA_NAME,
    )
