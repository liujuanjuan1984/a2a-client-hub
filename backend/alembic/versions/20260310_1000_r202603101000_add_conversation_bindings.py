"""add conversation bindings

Revision ID: r202603101000
Revises: r202603031200
Create Date: 2026-03-10 10:00:00.000000

"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r202603101000"
down_revision = "r202603031200"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    # Create conversation_bindings table
    op.create_table(
        "conversation_bindings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("binding_kind", sa.String(length=32), nullable=False, comment="Binding type: local_session, external_session, protocol_context."),
        sa.Column("provider", sa.String(length=64), nullable=True, comment="Provider name (e.g., 'opencode')."),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("agent_source", sa.String(length=16), nullable=True),
        sa.Column("local_session_id", sa.UUID(), nullable=True),
        sa.Column("external_session_id", sa.String(length=255), nullable=True),
        sa.Column("context_id", sa.String(length=255), nullable=True),
        sa.Column("binding_metadata", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], [f"{SCHEMA_NAME}.conversation_threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], [f"{SCHEMA_NAME}.users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "local_session_id", name="uq_conversation_bindings_local_session"),
        sa.UniqueConstraint("user_id", "provider", "agent_source", "agent_id", "external_session_id", name="uq_conversation_bindings_external_session"),
        schema=SCHEMA_NAME,
    )
    op.create_index("ix_conversation_bindings_conversation_primary", "conversation_bindings", ["conversation_id", "is_primary"], unique=False, schema=SCHEMA_NAME)
    op.create_index("ix_conversation_bindings_provider_context", "conversation_bindings", ["user_id", "provider", "context_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_agent_id"), "conversation_bindings", ["agent_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_binding_kind"), "conversation_bindings", ["binding_kind"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_context_id"), "conversation_bindings", ["context_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_conversation_id"), "conversation_bindings", ["conversation_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_external_session_id"), "conversation_bindings", ["external_session_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_local_session_id"), "conversation_bindings", ["local_session_id"], unique=False, schema=SCHEMA_NAME)
    op.create_index(op.f("ix_a2a_client_hub_schema_conversation_bindings_provider"), "conversation_bindings", ["provider"], unique=False, schema=SCHEMA_NAME)


def downgrade() -> None:
    op.drop_table("conversation_bindings", schema=SCHEMA_NAME)
