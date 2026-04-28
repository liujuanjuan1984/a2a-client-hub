"""Make A2A agent URL uniqueness ignore soft-deleted rows.

Revision ID: r202604281500
Revises: r202604220830
Create Date: 2026-04-28 15:00:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


revision = "r202604281500"
down_revision = "r202604220830"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")
TABLE_NAME = "a2a_agents"
UNIQUE_NAME = "uq_a2a_agents_user_scope_card_url"


def upgrade() -> None:
    op.drop_constraint(
        UNIQUE_NAME,
        TABLE_NAME,
        schema=SCHEMA_NAME,
        type_="unique",
    )
    op.create_index(
        UNIQUE_NAME,
        TABLE_NAME,
        ["user_id", "agent_scope", "card_url"],
        unique=True,
        schema=SCHEMA_NAME,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        UNIQUE_NAME,
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.create_unique_constraint(
        UNIQUE_NAME,
        TABLE_NAME,
        ["user_id", "agent_scope", "card_url"],
        schema=SCHEMA_NAME,
    )
