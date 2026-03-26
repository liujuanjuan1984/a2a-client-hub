"""add shared credential mode and hub user credentials

Revision ID: r202603261200
Revises: r202603250900
Create Date: 2026-03-26 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME

# revision identifiers, used by Alembic.
revision = "r202603261200"
down_revision = "r202603250900"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "a2a_agents",
        sa.Column(
            "credential_mode",
            sa.String(length=16),
            nullable=False,
            server_default="none",
            comment="Credential source mode (none/shared/user).",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_a2a_agents_credential_mode"),
        "a2a_agents",
        ["credential_mode"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.a2a_agents
            SET credential_mode = CASE
                WHEN agent_scope = 'shared' AND auth_type <> 'none' THEN 'shared'
                ELSE 'none'
            END
            """
        )
    )

    op.add_column(
        "a2a_agent_credentials",
        sa.Column(
            "username_hint",
            sa.String(length=120),
            nullable=True,
            comment="Non-secret username hint for basic auth credentials",
        ),
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "hub_a2a_user_credentials",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_type", sa.String(length=24), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("token_last4", sa.String(length=12), nullable=True),
        sa.Column("username_hint", sa.String(length=120), nullable=True),
        sa.Column(
            "encryption_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
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
            "agent_id",
            "user_id",
            name="uq_hub_a2a_user_credentials_agent_user",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_hub_a2a_user_credentials_agent_id"),
        "hub_a2a_user_credentials",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_hub_a2a_user_credentials_user_id"),
        "hub_a2a_user_credentials",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_hub_a2a_user_credentials_user_id"),
        table_name="hub_a2a_user_credentials",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_hub_a2a_user_credentials_agent_id"),
        table_name="hub_a2a_user_credentials",
        schema=SCHEMA_NAME,
    )
    op.drop_table("hub_a2a_user_credentials", schema=SCHEMA_NAME)

    op.drop_column("a2a_agent_credentials", "username_hint", schema=SCHEMA_NAME)

    op.drop_index(
        op.f("ix_a2a_agents_credential_mode"),
        table_name="a2a_agents",
        schema=SCHEMA_NAME,
    )
    op.drop_column("a2a_agents", "credential_mode", schema=SCHEMA_NAME)
