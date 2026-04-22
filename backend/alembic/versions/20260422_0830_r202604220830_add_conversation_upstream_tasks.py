"""Add durable conversation upstream task bindings.

Revision ID: r202604220830
Revises: r202604201030
Create Date: 2026-04-22 08:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "r202604220830"
down_revision = "r202604201030"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")
TABLE_NAME = "conversation_upstream_tasks"


def upgrade() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_source", sa.String(length=16), nullable=True),
        sa.Column("upstream_task_id", sa.String(length=255), nullable=False),
        sa.Column(
            "first_seen_message_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("latest_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "source",
            sa.String(length=32),
            server_default="stream_identity",
            nullable=False,
        ),
        sa.Column("status_hint", sa.String(length=32), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            [f"{SCHEMA_NAME}.conversation_threads.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["first_seen_message_id"],
            [f"{SCHEMA_NAME}.agent_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["latest_message_id"],
            [f"{SCHEMA_NAME}.agent_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "conversation_id",
            "upstream_task_id",
            name="uq_conversation_upstream_tasks_user_conversation_task",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_conversation_upstream_tasks_agent_id",
        TABLE_NAME,
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_conversation_upstream_tasks_user_id",
        TABLE_NAME,
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_conversation_upstream_tasks_user_conversation_updated",
        TABLE_NAME,
        ["user_id", "conversation_id", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_conversation_upstream_tasks_user_task",
        TABLE_NAME,
        ["user_id", "upstream_task_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA_NAME}.{TABLE_NAME} (
                id,
                user_id,
                conversation_id,
                agent_id,
                agent_source,
                upstream_task_id,
                first_seen_message_id,
                latest_message_id,
                source,
                status_hint,
                created_at,
                updated_at
            )
            SELECT
                (
                    SUBSTR(grouped.binding_hash, 1, 8) || '-' ||
                    SUBSTR(grouped.binding_hash, 9, 4) || '-' ||
                    SUBSTR(grouped.binding_hash, 13, 4) || '-' ||
                    SUBSTR(grouped.binding_hash, 17, 4) || '-' ||
                    SUBSTR(grouped.binding_hash, 21, 12)
                )::uuid,
                grouped.user_id,
                grouped.conversation_id,
                ct.agent_id,
                ct.agent_source,
                grouped.upstream_task_id,
                grouped.first_seen_message_id,
                grouped.latest_message_id,
                'metadata_backfill',
                grouped.status_hint,
                grouped.first_seen_at,
                grouped.latest_seen_at
            FROM (
                SELECT
                    am.user_id,
                    am.conversation_id,
                    BTRIM(am.metadata->>'upstream_task_id') AS upstream_task_id,
                    MD5(
                        am.user_id::text || ':' ||
                        am.conversation_id::text || ':' ||
                        BTRIM(am.metadata->>'upstream_task_id')
                    ) AS binding_hash,
                    (ARRAY_AGG(
                        am.id ORDER BY am.created_at ASC, am.id ASC
                    ))[1] AS first_seen_message_id,
                    (ARRAY_AGG(
                        am.id ORDER BY am.updated_at DESC, am.id DESC
                    ))[1] AS latest_message_id,
                    (ARRAY_AGG(
                        am.status ORDER BY am.updated_at DESC, am.id DESC
                    ))[1] AS status_hint,
                    MIN(am.created_at) AS first_seen_at,
                    MAX(am.updated_at) AS latest_seen_at
                FROM {SCHEMA_NAME}.agent_messages am
                WHERE am.metadata ? 'upstream_task_id'
                  AND NULLIF(BTRIM(am.metadata->>'upstream_task_id'), '') IS NOT NULL
                GROUP BY
                    am.user_id,
                    am.conversation_id,
                    BTRIM(am.metadata->>'upstream_task_id')
            ) grouped
            JOIN {SCHEMA_NAME}.conversation_threads ct
              ON ct.id = grouped.conversation_id
             AND ct.user_id = grouped.user_id
            ON CONFLICT (
                user_id,
                conversation_id,
                upstream_task_id
            ) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_upstream_tasks_user_task",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_conversation_upstream_tasks_user_conversation_updated",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_conversation_upstream_tasks_user_id",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_conversation_upstream_tasks_agent_id",
        table_name=TABLE_NAME,
        schema=SCHEMA_NAME,
    )
    op.drop_table(TABLE_NAME, schema=SCHEMA_NAME)
