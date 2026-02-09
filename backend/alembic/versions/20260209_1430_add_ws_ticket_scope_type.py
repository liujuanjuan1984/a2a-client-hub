"""add ws ticket scope type

Revision ID: 4b0a9c2e6d1f
Revises: 7a1d8f0c2b1a
Create Date: 2026-02-09 14:30:00.000000

"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "4b0a9c2e6d1f"
down_revision = "7a1d8f0c2b1a"
branch_labels = None
depends_on = None


SCHEMA = "a2a_client_hub_schema"


def upgrade() -> None:
    op.add_column(
        "ws_tickets",
        sa.Column(
            "scope_type",
            sa.String(length=32),
            nullable=True,
            comment="Scope type for this ticket (e.g., me_a2a_agent, hub_a2a_agent)",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_ws_tickets_scope_type",
        "ws_tickets",
        ["scope_type"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_ws_tickets_scope_type", table_name="ws_tickets", schema=SCHEMA)
    op.drop_column("ws_tickets", "scope_type", schema=SCHEMA)

