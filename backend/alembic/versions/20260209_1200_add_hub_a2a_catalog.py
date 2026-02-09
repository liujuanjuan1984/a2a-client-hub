"""add hub a2a catalog and ws ticket scoping

Revision ID: 6c0a9a8e7f5a
Revises: 30b3bfe6c067
Create Date: 2026-02-09 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6c0a9a8e7f5a"
down_revision = "30b3bfe6c067"
branch_labels = None
depends_on = None


SCHEMA = "a2a_client_hub_schema"


def upgrade() -> None:
    op.create_table(
        "hub_a2a_agents",
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            comment="Admin-managed label for the hub A2A agent",
        ),
        sa.Column(
            "card_url",
            sa.String(length=1024),
            nullable=False,
            comment="Agent card URL",
        ),
        sa.Column(
            "availability_policy",
            sa.String(length=32),
            server_default="public",
            nullable=False,
            comment="Availability policy (public/allowlist)",
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
            comment="Whether this hub agent is enabled for invocation",
        ),
        sa.Column(
            "tags",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Optional tags as JSON array",
        ),
        sa.Column(
            "extra_headers",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=True,
            comment="Additional headers to include when fetching card/invoking",
        ),
        sa.Column(
            "created_by_user_id",
            sa.UUID(),
            nullable=False,
            comment="Admin user id that created this agent",
        ),
        sa.Column(
            "updated_by_user_id",
            sa.UUID(),
            nullable=True,
            comment="Admin user id that last updated this agent",
        ),
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key (UUID v4)"),
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
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )

    op.create_table(
        "hub_a2a_agent_credentials",
        sa.Column("agent_id", sa.UUID(), nullable=False, comment="Related hub A2A agent id"),
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
            "created_by_user_id",
            sa.UUID(),
            nullable=False,
            comment="Admin user id that created/updated the credential",
        ),
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key (UUID v4)"),
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
        sa.ForeignKeyConstraint(
            ["agent_id"],
            [f"{SCHEMA}.hub_a2a_agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", name="uq_hub_a2a_agent_credentials_agent"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hub_a2a_agent_credentials_agent_id",
        "hub_a2a_agent_credentials",
        ["agent_id"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "hub_a2a_agent_allowlist",
        sa.Column("agent_id", sa.UUID(), nullable=False, comment="Related hub A2A agent id"),
        sa.Column("user_id", sa.UUID(), nullable=False, comment="Allowlisted user id"),
        sa.Column(
            "created_by_user_id",
            sa.UUID(),
            nullable=False,
            comment="Admin user id that created the allowlist entry",
        ),
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key (UUID v4)"),
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
        sa.ForeignKeyConstraint(
            ["agent_id"],
            [f"{SCHEMA}.hub_a2a_agents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id",
            "user_id",
            name="uq_hub_a2a_agent_allowlist_agent_user",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hub_a2a_agent_allowlist_agent_id",
        "hub_a2a_agent_allowlist",
        ["agent_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hub_a2a_agent_allowlist_user_id",
        "hub_a2a_agent_allowlist",
        ["user_id"],
        unique=False,
        schema=SCHEMA,
    )

    # ws_tickets.agent_id must be usable for both user-managed agents and hub agents.
    # Drop the FK constraint to a2a_agents and treat it as a generic scope id.
    op.execute(
        f"ALTER TABLE {SCHEMA}.ws_tickets "
        "DROP CONSTRAINT IF EXISTS ws_tickets_agent_id_fkey"
    )
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

    op.drop_index(
        "ix_hub_a2a_agent_allowlist_user_id",
        table_name="hub_a2a_agent_allowlist",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_hub_a2a_agent_allowlist_agent_id",
        table_name="hub_a2a_agent_allowlist",
        schema=SCHEMA,
    )
    op.drop_table("hub_a2a_agent_allowlist", schema=SCHEMA)

    op.drop_index(
        "ix_hub_a2a_agent_credentials_agent_id",
        table_name="hub_a2a_agent_credentials",
        schema=SCHEMA,
    )
    op.drop_table("hub_a2a_agent_credentials", schema=SCHEMA)

    op.drop_table("hub_a2a_agents", schema=SCHEMA)
