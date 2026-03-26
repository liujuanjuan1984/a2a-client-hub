"""Store auth_type on hub user credentials for compatibility checks."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.db.models.base import SCHEMA_NAME


revision = "r202603261700"
down_revision = "r202603261200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hub_a2a_user_credentials",
        sa.Column("auth_type", sa.String(length=24), nullable=True),
        schema=SCHEMA_NAME,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.hub_a2a_user_credentials AS cred
            SET auth_type = agent.auth_type
            FROM {SCHEMA_NAME}.a2a_agents AS agent
            WHERE agent.id = cred.agent_id
            """
        )
    )
    op.alter_column(
        "hub_a2a_user_credentials",
        "auth_type",
        existing_type=sa.String(length=24),
        nullable=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column("hub_a2a_user_credentials", "auth_type", schema=SCHEMA_NAME)
