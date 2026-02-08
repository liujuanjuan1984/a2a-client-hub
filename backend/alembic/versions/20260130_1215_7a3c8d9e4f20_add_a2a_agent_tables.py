"""add a2a agent tables

Revision ID: 7a3c8d9e4f20
Revises: 9c8b7a6d5e4f
Create Date: 2026-01-30 12:15:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "7a3c8d9e4f20"
down_revision = "9c8b7a6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "a2a_agents",
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            comment="User-facing label for the A2A agent",
        ),
        sa.Column(
            "card_url",
            sa.String(length=1024),
            nullable=False,
            comment="Agent card URL",
        ),
        sa.Column(
            "auth_type",
            sa.String(length=32),
            server_default="none",
            nullable=False,
            comment="Authentication type (none/bearer)",
        ),
        sa.Column(
            "auth_header",
            sa.String(length=120),
            nullable=True,
            comment="HTTP header name for auth (e.g., Authorization)",
        ),
        sa.Column(
            "auth_scheme",
            sa.String(length=64),
            nullable=True,
            comment="Authentication scheme (e.g., Bearer)",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default="true",
            nullable=False,
            comment="Whether this agent is enabled for invocation",
        ),
        sa.Column(
            "tags",
            sa.JSON(),
            nullable=True,
            comment="Optional tags as JSON array",
        ),
        sa.Column(
            "extra_headers",
            sa.JSON(),
            nullable=True,
            comment="Additional headers to include when fetching card/invoking",
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
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete timestamp (NULL means not deleted)",
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "card_url",
            name="uq_a2a_agents_user_card_url",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_agents_user_id"),
        "a2a_agents",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "a2a_agent_credentials",
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=False,
            comment="Related A2A agent id",
        ),
        sa.Column(
            "encrypted_token",
            sa.Text(),
            nullable=False,
            comment="Encrypted bearer token (Fernet)",
        ),
        sa.Column(
            "token_last4",
            sa.String(length=12),
            nullable=True,
            comment="Last four characters of the token for display",
        ),
        sa.Column(
            "encryption_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="Secret encryption version",
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
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft delete timestamp (NULL means not deleted)",
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
        sa.UniqueConstraint(
            "user_id",
            "agent_id",
            name="uq_a2a_agent_credentials_user_agent",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_agent_credentials_agent_id"),
        "a2a_agent_credentials",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_agent_credentials_user_id"),
        "a2a_agent_credentials",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_agent_credentials_user_id"),
        table_name="a2a_agent_credentials",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_agent_credentials_agent_id"),
        table_name="a2a_agent_credentials",
        schema=SCHEMA_NAME,
    )
    op.drop_table("a2a_agent_credentials", schema=SCHEMA_NAME)
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_agents_user_id"),
        table_name="a2a_agents",
        schema=SCHEMA_NAME,
    )
    op.drop_table("a2a_agents", schema=SCHEMA_NAME)
