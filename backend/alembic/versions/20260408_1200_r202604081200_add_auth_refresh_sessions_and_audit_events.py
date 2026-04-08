"""add auth refresh sessions and audit events

Revision ID: r202604081200
Revises: r202604071100
Create Date: 2026-04-08 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME

# revision identifiers, used by Alembic.
revision = "r202604081200"
down_revision = "r202604071100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "legacy_refresh_valid_after",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Legacy refresh tokens issued at or before this timestamp are invalid"
            ),
        ),
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "auth_refresh_sessions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("current_jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip", sa.String(length=64), nullable=True),
        sa.Column("created_user_agent", sa.String(length=512), nullable=True),
        sa.Column("last_seen_ip", sa.String(length=64), nullable=True),
        sa.Column("last_seen_user_agent", sa.String(length=512), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
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
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("current_jti", name="uq_auth_refresh_sessions_current_jti"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_auth_refresh_sessions_current_jti"),
        "auth_refresh_sessions",
        ["current_jti"],
        unique=True,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_auth_refresh_sessions_revoked_at"),
        "auth_refresh_sessions",
        ["revoked_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_auth_refresh_sessions_user_id"),
        "auth_refresh_sessions",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_auth_refresh_sessions_user_id_revoked_at",
        "auth_refresh_sessions",
        ["user_id", "revoked_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "auth_audit_events",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_jti", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
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
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_auth_audit_events_user_id"),
        "auth_audit_events",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_auth_audit_events_user_id_created_at",
        "auth_audit_events",
        ["user_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_auth_audit_events_event_type_created_at",
        "auth_audit_events",
        ["event_type", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_audit_events_event_type_created_at",
        table_name="auth_audit_events",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_auth_audit_events_user_id_created_at",
        table_name="auth_audit_events",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_auth_audit_events_user_id"),
        table_name="auth_audit_events",
        schema=SCHEMA_NAME,
    )
    op.drop_table("auth_audit_events", schema=SCHEMA_NAME)

    op.drop_index(
        "ix_auth_refresh_sessions_user_id_revoked_at",
        table_name="auth_refresh_sessions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_auth_refresh_sessions_user_id"),
        table_name="auth_refresh_sessions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_auth_refresh_sessions_revoked_at"),
        table_name="auth_refresh_sessions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_auth_refresh_sessions_current_jti"),
        table_name="auth_refresh_sessions",
        schema=SCHEMA_NAME,
    )
    op.drop_table("auth_refresh_sessions", schema=SCHEMA_NAME)
    op.drop_column("users", "legacy_refresh_valid_after", schema=SCHEMA_NAME)
