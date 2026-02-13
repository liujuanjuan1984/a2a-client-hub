"""add canonical conversation threads and bindings

Revision ID: a43f9b7d1d6e
Revises: 6814c222efe9
Create Date: 2026-02-13 11:25:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a43f9b7d1d6e"
down_revision = "6814c222efe9"
branch_labels = None
depends_on = None


SCHEMA = "a2a_client_hub_schema"


def upgrade() -> None:
    op.create_table(
        "conversation_threads",
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=True,
            comment="Agent id associated with this thread (nullable for legacy rows).",
        ),
        sa.Column(
            "agent_source",
            sa.String(length=16),
            nullable=True,
            comment="Agent source scope (personal/shared).",
        ),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="Session"),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
            comment="Thread lifecycle status: active/merged/archived.",
        ),
        sa.Column(
            "merged_into_id",
            sa.UUID(),
            nullable=True,
            comment="If merged, points to the surviving canonical thread.",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=True,
            comment="Optional internal notes for merge/audit operations.",
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
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            [f"{SCHEMA}.conversation_threads.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_threads_user_id",
        "conversation_threads",
        ["user_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_threads_agent_id",
        "conversation_threads",
        ["agent_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_threads_last_active_at",
        "conversation_threads",
        ["last_active_at"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "conversation_bindings",
        sa.Column(
            "conversation_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "binding_kind",
            sa.String(length=32),
            nullable=False,
            comment="Binding kind: local_session/external_session/protocol_context.",
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=True,
            comment="External provider key (e.g., opencode).",
        ),
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=True,
            comment="Agent id for scoping external bindings.",
        ),
        sa.Column(
            "agent_source",
            sa.String(length=16),
            nullable=True,
            comment="Agent source scope (personal/shared).",
        ),
        sa.Column("local_session_id", sa.UUID(), nullable=True),
        sa.Column(
            "external_session_id",
            sa.String(length=255),
            nullable=True,
            comment="External provider session identifier.",
        ),
        sa.Column(
            "context_id",
            sa.String(length=255),
            nullable=True,
            comment="Protocol context identifier (A2A contextId).",
        ),
        sa.Column(
            "binding_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Provider-specific binding metadata.",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="1.0",
            comment="Binding confidence for reconciliation workflows.",
        ),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            comment="Whether this binding is the primary locator for the conversation.",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
            comment="Binding lifecycle status: active/stale.",
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{SCHEMA}.conversation_threads.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["local_session_id"],
            [f"{SCHEMA}.agent_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA}.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_user_id",
        "conversation_bindings",
        ["user_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_conversation_id",
        "conversation_bindings",
        ["conversation_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_provider",
        "conversation_bindings",
        ["provider"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_agent_id",
        "conversation_bindings",
        ["agent_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_local_session_id",
        "conversation_bindings",
        ["local_session_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_external_session_id",
        "conversation_bindings",
        ["external_session_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_context_id",
        "conversation_bindings",
        ["context_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_conversation_bindings_last_seen_at",
        "conversation_bindings",
        ["last_seen_at"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "uq_conversation_bindings_user_local_active",
        "conversation_bindings",
        ["user_id", "local_session_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'active' AND local_session_id IS NOT NULL"),
    )
    op.create_index(
        "uq_conversation_bindings_user_provider_external_active",
        "conversation_bindings",
        ["user_id", "provider", "agent_source", "agent_id", "external_session_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(
            "status = 'active' AND provider IS NOT NULL AND external_session_id IS NOT NULL"
        ),
    )

    op.add_column(
        "agent_messages",
        sa.Column(
            "conversation_id",
            sa.UUID(),
            nullable=True,
            comment="Canonical conversation identifier used for cross-source dedup.",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "fk_agent_messages_conversation_id",
        "agent_messages",
        "conversation_threads",
        ["conversation_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_messages_conversation_id",
        "agent_messages",
        ["conversation_id"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_messages_conversation_id",
        table_name="agent_messages",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "fk_agent_messages_conversation_id",
        "agent_messages",
        schema=SCHEMA,
        type_="foreignkey",
    )
    op.drop_column("agent_messages", "conversation_id", schema=SCHEMA)

    op.drop_index(
        "uq_conversation_bindings_user_provider_external_active",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "uq_conversation_bindings_user_local_active",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_last_seen_at",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_context_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_external_session_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_local_session_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_agent_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_provider",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_conversation_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_bindings_user_id",
        table_name="conversation_bindings",
        schema=SCHEMA,
    )
    op.drop_table("conversation_bindings", schema=SCHEMA)

    op.drop_index(
        "ix_conversation_threads_last_active_at",
        table_name="conversation_threads",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_threads_agent_id",
        table_name="conversation_threads",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_conversation_threads_user_id",
        table_name="conversation_threads",
        schema=SCHEMA,
    )
    op.drop_table("conversation_threads", schema=SCHEMA)
