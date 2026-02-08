"""add ws tickets

Revision ID: 6b1f3c2d4e5f
Revises: 8f2d3c4b5a61
Create Date: 2026-02-01 14:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "6b1f3c2d4e5f"
down_revision = "8f2d3c4b5a61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ws_tickets",
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=False,
            comment="A2A agent bound to the ticket",
        ),
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
            comment="HMAC-SHA256 hash of the WS ticket",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Ticket expiration timestamp",
        ),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Timestamp when the ticket was consumed",
        ),
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
            comment="Primary key (UUID v4)",
        ),
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
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            [f"{SCHEMA_NAME}.a2a_agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_ws_tickets_token_hash"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_ws_tickets_agent_id"),
        "ws_tickets",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_ws_tickets_expires_at"),
        "ws_tickets",
        ["expires_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_ws_tickets_user_id"),
        "ws_tickets",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_common_compass_schema_ws_tickets_user_id"),
        table_name="ws_tickets",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_ws_tickets_expires_at"),
        table_name="ws_tickets",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_ws_tickets_agent_id"),
        table_name="ws_tickets",
        schema=SCHEMA_NAME,
    )
    op.drop_table("ws_tickets", schema=SCHEMA_NAME)
