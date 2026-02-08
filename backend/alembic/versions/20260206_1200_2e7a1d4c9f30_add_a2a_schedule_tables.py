"""add a2a schedule tables

Revision ID: 2e7a1d4c9f30
Revises: 6b1f3c2d4e5f
Create Date: 2026-02-06 12:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "2e7a1d4c9f30"
down_revision = "6b1f3c2d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "a2a_schedule_tasks",
        sa.Column(
            "name",
            sa.String(length=120),
            nullable=False,
            comment="User-facing task name",
        ),
        sa.Column(
            "agent_id",
            sa.UUID(),
            nullable=False,
            comment="Target A2A agent identifier",
        ),
        sa.Column(
            "session_id",
            sa.UUID(),
            nullable=True,
            comment="Scheduled session used to store recurring conversation messages",
        ),
        sa.Column(
            "prompt",
            sa.Text(),
            nullable=False,
            comment="Prompt sent to the target agent on each run",
        ),
        sa.Column(
            "cycle_type",
            sa.String(length=16),
            nullable=False,
            comment="Cycle type: daily/weekly/monthly",
        ),
        sa.Column(
            "time_point",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Cycle-specific trigger point definition",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
            comment="Whether the schedule is active",
        ),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Next planned trigger time in UTC",
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Most recent execution completion time in UTC",
        ),
        sa.Column(
            "last_run_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'idle'"),
            comment="Status of the most recent execution",
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
            ["session_id"],
            [f"{SCHEMA_NAME}.agent_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_agent_id"),
        "a2a_schedule_tasks",
        ["agent_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_schedule_tasks_due",
        "a2a_schedule_tasks",
        ["user_id", "enabled", "next_run_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_next_run_at"),
        "a2a_schedule_tasks",
        ["next_run_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_session_id"),
        "a2a_schedule_tasks",
        ["session_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_user_id"),
        "a2a_schedule_tasks",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    op.create_table(
        "a2a_schedule_executions",
        sa.Column(
            "task_id",
            sa.UUID(),
            nullable=False,
            comment="Owning schedule task identifier",
        ),
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Planned trigger time for this execution",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="Execution start time",
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Execution completion time",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'running'"),
            comment="Execution status",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
            comment="Failure reason if execution did not succeed",
        ),
        sa.Column(
            "response_content",
            sa.Text(),
            nullable=True,
            comment="Persisted response content returned by the target agent",
        ),
        sa.Column(
            "session_id",
            sa.UUID(),
            nullable=True,
            comment="Associated scheduled session",
        ),
        sa.Column(
            "user_message_id",
            sa.UUID(),
            nullable=True,
            comment="Generated user-side message ID",
        ),
        sa.Column(
            "agent_message_id",
            sa.UUID(),
            nullable=True,
            comment="Generated agent-side message ID",
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
            ["task_id"],
            [f"{SCHEMA_NAME}.a2a_schedule_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            [f"{SCHEMA_NAME}.agent_sessions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"],
            [f"{SCHEMA_NAME}.agent_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_message_id"],
            [f"{SCHEMA_NAME}.agent_messages.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            [f"{SCHEMA_NAME}.users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_agent_message_id"),
        "a2a_schedule_executions",
        ["agent_message_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        "ix_a2a_schedule_executions_task_created",
        "a2a_schedule_executions",
        ["task_id", "created_at"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_session_id"),
        "a2a_schedule_executions",
        ["session_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_task_id"),
        "a2a_schedule_executions",
        ["task_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_user_id"),
        "a2a_schedule_executions",
        ["user_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_user_message_id"),
        "a2a_schedule_executions",
        ["user_message_id"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_user_message_id"),
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_user_id"),
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_task_id"),
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_session_id"),
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_a2a_schedule_executions_task_created",
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_executions_agent_message_id"),
        table_name="a2a_schedule_executions",
        schema=SCHEMA_NAME,
    )
    op.drop_table("a2a_schedule_executions", schema=SCHEMA_NAME)

    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_user_id"),
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_session_id"),
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_next_run_at"),
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        "ix_a2a_schedule_tasks_due",
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_a2a_schedule_tasks_agent_id"),
        table_name="a2a_schedule_tasks",
        schema=SCHEMA_NAME,
    )
    op.drop_table("a2a_schedule_tasks", schema=SCHEMA_NAME)
