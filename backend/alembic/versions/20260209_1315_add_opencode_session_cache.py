"""add opencode session cache

Revision ID: 6814c222efe9
Revises: 6c0a9a8e7f5a
Create Date: 2026-02-09 13:15:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "6814c222efe9"
down_revision = "6c0a9a8e7f5a"
branch_labels = None
depends_on = None


SCHEMA = "a2a_client_hub_schema"


def upgrade() -> None:
    op.create_table(
        "opencode_session_cache",
        sa.Column(
            "user_id",
            sa.UUID(),
            nullable=False,
            comment="Cache owner (UUID)",
        ),
        sa.Column(
            "agent_source",
            sa.String(length=16),
            nullable=False,
            comment="Agent source scope (personal/shared)",
        ),
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=False,
            comment="Agent id (UUID)",
        ),
        sa.Column(
            "payload",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            comment="Cached session list payload (minimal snapshot)",
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Cache expiry timestamp",
        ),
        sa.Column(
            "last_success_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time this cache entry was refreshed successfully",
        ),
        sa.Column(
            "last_error_code",
            sa.String(length=64),
            nullable=True,
            comment="Last upstream error_code observed during refresh (best-effort)",
        ),
        sa.Column(
            "last_error_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time an upstream error was observed during refresh",
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="Last time this cache entry payload was written",
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
            ["user_id"],
            [f"{SCHEMA}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "agent_source",
            "agent_id",
            name="uq_opencode_session_cache_user_source_agent",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opencode_session_cache_user_id",
        "opencode_session_cache",
        ["user_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opencode_session_cache_agent_id",
        "opencode_session_cache",
        ["agent_id"],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        "ix_opencode_session_cache_expires_at",
        "opencode_session_cache",
        ["expires_at"],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_opencode_session_cache_expires_at",
        table_name="opencode_session_cache",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_opencode_session_cache_agent_id",
        table_name="opencode_session_cache",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_opencode_session_cache_user_id",
        table_name="opencode_session_cache",
        schema=SCHEMA,
    )
    op.drop_table("opencode_session_cache", schema=SCHEMA)

