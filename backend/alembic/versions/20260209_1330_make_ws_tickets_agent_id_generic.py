"""make ws tickets agent id generic

Revision ID: 7a1d8f0c2b1a
Revises: 6c0a9a8e7f5a
Create Date: 2026-02-09 13:30:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "7a1d8f0c2b1a"
down_revision = "6c0a9a8e7f5a"
branch_labels = None
depends_on = None


SCHEMA = "a2a_client_hub_schema"


def upgrade() -> None:
    # ws_tickets.agent_id must be usable for both user-managed agents and hub agents.
    # Dropping the FK constraint makes the column a generic scope identifier.
    op.execute(
        f"ALTER TABLE {SCHEMA}.ws_tickets "
        "DROP CONSTRAINT IF EXISTS ws_tickets_agent_id_fkey"
    )


def downgrade() -> None:
    op.create_foreign_key(
        "ws_tickets_agent_id_fkey",
        "ws_tickets",
        "a2a_agents",
        ["agent_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="CASCADE",
    )

