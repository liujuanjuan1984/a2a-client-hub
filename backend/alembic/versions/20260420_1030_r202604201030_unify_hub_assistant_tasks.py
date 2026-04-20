"""Unify Hub Assistant durable tasks into one table.

Revision ID: r202604201030
Revises: r202604161200
Create Date: 2026-04-20 10:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "r202604201030"
down_revision = "r202604161200"
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")

_FOLLOW_UP_KIND = "follow_up_watch"
_TASK_TABLE_NAME = "hub_assistant_tasks"
_FOLLOW_UP_TABLE_CANDIDATES = (
    "hub_assistant_follow_up_tasks",
    "built_in_follow_up_tasks",
)
_CONVERSATION_COLUMN_CANDIDATES = (
    "hub_assistant_conversation_id",
    "built_in_conversation_id",
)


def _get_inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _get_inspector().get_table_names(schema=SCHEMA_NAME)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in _get_inspector().get_columns(table_name, schema=SCHEMA_NAME)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in _get_inspector().get_indexes(table_name, schema=SCHEMA_NAME)
    )


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in _get_inspector().get_unique_constraints(
            table_name,
            schema=SCHEMA_NAME,
        )
    )


def _has_foreign_key_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in _get_inspector().get_foreign_keys(
            table_name,
            schema=SCHEMA_NAME,
        )
    )


def _drop_index_if_exists(table_name: str, index_name: str) -> None:
    if _has_index(table_name, index_name):
        op.drop_index(
            index_name,
            table_name=table_name,
            schema=SCHEMA_NAME,
        )


def _drop_indexes_by_columns(table_name: str, *column_names: str) -> None:
    target_columns = tuple(column_names)
    for index in _get_inspector().get_indexes(table_name, schema=SCHEMA_NAME):
        if tuple(index.get("column_names") or ()) != target_columns:
            continue
        op.drop_index(
            index["name"],
            table_name=table_name,
            schema=SCHEMA_NAME,
        )


def _drop_unique_constraint_if_exists(
    table_name: str,
    constraint_name: str,
) -> None:
    if _has_unique_constraint(table_name, constraint_name):
        op.drop_constraint(
            constraint_name,
            table_name,
            schema=SCHEMA_NAME,
            type_="unique",
        )


def _drop_unique_constraints_by_columns(table_name: str, *column_names: str) -> None:
    target_columns = tuple(column_names)
    for constraint in _get_inspector().get_unique_constraints(
        table_name,
        schema=SCHEMA_NAME,
    ):
        if tuple(constraint.get("column_names") or ()) != target_columns:
            continue
        op.drop_constraint(
            constraint["name"],
            table_name,
            schema=SCHEMA_NAME,
            type_="unique",
        )


def _drop_foreign_key_constraint_if_exists(
    table_name: str,
    constraint_name: str,
) -> None:
    if _has_foreign_key_constraint(table_name, constraint_name):
        op.drop_constraint(
            constraint_name,
            table_name,
            schema=SCHEMA_NAME,
            type_="foreignkey",
        )


def _drop_foreign_keys_by_columns(table_name: str, *column_names: str) -> None:
    target_columns = tuple(column_names)
    for constraint in _get_inspector().get_foreign_keys(
        table_name,
        schema=SCHEMA_NAME,
    ):
        if tuple(constraint.get("constrained_columns") or ()) != target_columns:
            continue
        op.drop_constraint(
            constraint["name"],
            table_name,
            schema=SCHEMA_NAME,
            type_="foreignkey",
        )


def _resolve_follow_up_table_name() -> str:
    for table_name in _FOLLOW_UP_TABLE_CANDIDATES:
        if _has_table(table_name):
            return table_name
    raise RuntimeError("Hub Assistant follow-up task table is missing")


def _resolve_conversation_column_name(table_name: str) -> str:
    for column_name in _CONVERSATION_COLUMN_CANDIDATES:
        if _has_column(table_name, column_name):
            return column_name
    raise RuntimeError(
        f"Hub Assistant follow-up task conversation column is missing on {table_name}"
    )


def upgrade() -> None:
    follow_up_table_name = _resolve_follow_up_table_name()
    if follow_up_table_name != _TASK_TABLE_NAME:
        op.rename_table(
            follow_up_table_name,
            _TASK_TABLE_NAME,
            schema=SCHEMA_NAME,
        )

    conversation_column_name = _resolve_conversation_column_name(_TASK_TABLE_NAME)
    if conversation_column_name != "hub_assistant_conversation_id":
        _drop_foreign_key_constraint_if_exists(
            _TASK_TABLE_NAME,
            f"{follow_up_table_name}_{conversation_column_name}_fkey",
        )
        _drop_foreign_keys_by_columns(_TASK_TABLE_NAME, conversation_column_name)
        op.alter_column(
            _TASK_TABLE_NAME,
            conversation_column_name,
            new_column_name="hub_assistant_conversation_id",
            existing_type=postgresql.UUID(as_uuid=True),
            schema=SCHEMA_NAME,
        )
        op.create_foreign_key(
            f"{_TASK_TABLE_NAME}_hub_assistant_conversation_id_fkey",
            _TASK_TABLE_NAME,
            "conversation_threads",
            ["hub_assistant_conversation_id"],
            ["id"],
            source_schema=SCHEMA_NAME,
            referent_schema=SCHEMA_NAME,
            ondelete="CASCADE",
        )

    for constraint_name in (
        "uq_built_in_follow_up_tasks_user_conversation",
        "uq_hub_assistant_follow_up_tasks_user_conversation",
    ):
        _drop_unique_constraint_if_exists(_TASK_TABLE_NAME, constraint_name)
    _drop_unique_constraints_by_columns(
        _TASK_TABLE_NAME,
        "user_id",
        "hub_assistant_conversation_id",
    )

    for index_name in (
        "ix_built_in_follow_up_tasks_status_updated_at",
        "ix_built_in_follow_up_tasks_conversation_status",
        "ix_hub_assistant_follow_up_tasks_status_updated_at",
        "ix_hub_assistant_follow_up_tasks_conversation_status",
    ):
        _drop_index_if_exists(_TASK_TABLE_NAME, index_name)
    _drop_indexes_by_columns(_TASK_TABLE_NAME, "user_id")
    _drop_indexes_by_columns(_TASK_TABLE_NAME, "hub_assistant_conversation_id")

    if not _has_column(_TASK_TABLE_NAME, "task_kind"):
        op.add_column(
            _TASK_TABLE_NAME,
            sa.Column(
                "task_kind",
                sa.String(length=64),
                nullable=True,
                comment="Hub Assistant task kind.",
            ),
            schema=SCHEMA_NAME,
        )
    if not _has_column(_TASK_TABLE_NAME, "dedupe_key"):
        op.add_column(
            _TASK_TABLE_NAME,
            sa.Column(
                "dedupe_key",
                sa.String(length=255),
                nullable=True,
                comment="Optional idempotency key used to deduplicate tasks.",
            ),
            schema=SCHEMA_NAME,
        )
    if not _has_column(_TASK_TABLE_NAME, "task_payload"):
        op.add_column(
            _TASK_TABLE_NAME,
            sa.Column(
                "task_payload",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
                comment="Serialized background task payload.",
            ),
            schema=SCHEMA_NAME,
        )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.{_TASK_TABLE_NAME}
            SET task_kind = :task_kind,
                task_payload = jsonb_build_object(
                    'tracked_conversation_ids',
                    COALESCE(tracked_conversation_ids, '[]'::jsonb),
                    'target_agent_message_anchors',
                    COALESCE(target_agent_message_anchors, '{{}}'::jsonb)
                )
            WHERE task_kind IS NULL
            """
        ).bindparams(task_kind=_FOLLOW_UP_KIND)
    )

    op.alter_column(
        _TASK_TABLE_NAME,
        "task_kind",
        existing_type=sa.String(length=64),
        nullable=False,
        schema=SCHEMA_NAME,
    )
    op.alter_column(
        _TASK_TABLE_NAME,
        "task_payload",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        schema=SCHEMA_NAME,
    )

    if _has_column(_TASK_TABLE_NAME, "tracked_conversation_ids"):
        op.drop_column(
            _TASK_TABLE_NAME,
            "tracked_conversation_ids",
            schema=SCHEMA_NAME,
        )
    if _has_column(_TASK_TABLE_NAME, "target_agent_message_anchors"):
        op.drop_column(
            _TASK_TABLE_NAME,
            "target_agent_message_anchors",
            schema=SCHEMA_NAME,
        )

    if not _has_unique_constraint(_TASK_TABLE_NAME, "uq_hub_assistant_tasks_dedupe_key"):
        op.create_unique_constraint(
            "uq_hub_assistant_tasks_dedupe_key",
            _TASK_TABLE_NAME,
            ["dedupe_key"],
            schema=SCHEMA_NAME,
        )
    if not _has_index(_TASK_TABLE_NAME, "ix_hub_assistant_tasks_status_updated_at"):
        op.create_index(
            "ix_hub_assistant_tasks_status_updated_at",
            _TASK_TABLE_NAME,
            ["status", "updated_at"],
            unique=False,
            schema=SCHEMA_NAME,
        )
    if not _has_index(_TASK_TABLE_NAME, "ix_hub_assistant_tasks_kind_status"):
        op.create_index(
            "ix_hub_assistant_tasks_kind_status",
            _TASK_TABLE_NAME,
            ["task_kind", "status"],
            unique=False,
            schema=SCHEMA_NAME,
        )
    if not _has_index(
        _TASK_TABLE_NAME,
        "ix_hub_assistant_tasks_conversation_kind_status",
    ):
        op.create_index(
            "ix_hub_assistant_tasks_conversation_kind_status",
            _TASK_TABLE_NAME,
            ["hub_assistant_conversation_id", "task_kind", "status"],
            unique=False,
            schema=SCHEMA_NAME,
        )
    if not _has_index(_TASK_TABLE_NAME, "uq_hub_assistant_tasks_follow_up_conversation"):
        op.create_index(
            "uq_hub_assistant_tasks_follow_up_conversation",
            _TASK_TABLE_NAME,
            ["user_id", "hub_assistant_conversation_id"],
            unique=True,
            schema=SCHEMA_NAME,
            postgresql_where=sa.text(f"task_kind = '{_FOLLOW_UP_KIND}'"),
        )

    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.conversation_threads
            SET agent_source = 'hub_assistant'
            WHERE agent_source = 'builtin'
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.user_agent_availability_snapshots
            SET agent_source = 'hub_assistant'
            WHERE agent_source = 'builtin'
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE {SCHEMA_NAME}.user_agent_availability_snapshots
            SET agent_id = 'hub-assistant'
            WHERE agent_id = 'self-management-assistant'
            """
        )
    )


def downgrade() -> None:
    op.create_table(
        "built_in_follow_up_tasks",
        sa.Column(
            "built_in_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_NAME}.conversation_threads.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            comment="Built-in conversation that owns this follow-up substrate.",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting",
            comment="Lifecycle status for the durable follow-up substrate.",
        ),
        sa.Column(
            "tracked_conversation_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
            comment="Current target conversation ids tracked by the built-in agent.",
        ),
        sa.Column(
            "target_agent_message_anchors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
            comment="Latest observed target-agent text message id per tracked conversation.",
        ),
        sa.Column(
            "last_run_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent follow-up run started.",
        ),
        sa.Column(
            "last_run_finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the most recent follow-up run finished.",
        ),
        sa.Column(
            "last_run_error",
            sa.String(length=255),
            nullable=True,
            comment="Most recent background follow-up execution error, if any.",
        ),
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            primary_key=True,
            comment="Primary key (UUID v4)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Record creation timestamp",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="Record last update timestamp",
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
            nullable=False,
            comment="Data owner (UUID)",
        ),
        sa.UniqueConstraint(
            "user_id",
            "built_in_conversation_id",
            name="uq_built_in_follow_up_tasks_user_conversation",
        ),
        schema=SCHEMA_NAME,
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {SCHEMA_NAME}.built_in_follow_up_tasks (
                id,
                created_at,
                updated_at,
                user_id,
                built_in_conversation_id,
                status,
                tracked_conversation_ids,
                target_agent_message_anchors,
                last_run_started_at,
                last_run_finished_at,
                last_run_error
            )
            SELECT
                id,
                created_at,
                updated_at,
                user_id,
                hub_assistant_conversation_id,
                status,
                COALESCE(task_payload -> 'tracked_conversation_ids', '[]'::jsonb),
                COALESCE(task_payload -> 'target_agent_message_anchors', '{{}}'::jsonb),
                last_run_started_at,
                last_run_finished_at,
                last_run_error
            FROM {SCHEMA_NAME}.hub_assistant_tasks
            WHERE task_kind = :task_kind
            """
        ).bindparams(task_kind=_FOLLOW_UP_KIND)
    )

    op.create_index(
        "ix_built_in_follow_up_tasks_status_updated_at",
        "built_in_follow_up_tasks",
        ["status", "updated_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_built_in_follow_up_tasks_conversation_status",
        "built_in_follow_up_tasks",
        ["built_in_conversation_id", "status"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_built_in_follow_up_tasks_conversation",
        "built_in_follow_up_tasks",
        ["built_in_conversation_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_built_in_follow_up_tasks_user_id",
        "built_in_follow_up_tasks",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.drop_table("hub_assistant_tasks", schema=SCHEMA_NAME)
