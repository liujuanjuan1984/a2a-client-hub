"""Add pending status to a2a_schedule_executions

Revision ID: f0d714e35080
Revises: r202603031200
Create Date: 2026-03-11 12:15:02.113820

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'f0d714e35080'
down_revision = 'r202603031200'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Adding pending status is just a string update (since we use VARCHAR, not strict ENUM).
    # We will add an index on (status, scheduled_for) to optimize skip-locked polling for the consumer.
    op.create_index(
        "ix_a2a_schedule_executions_queue_poll",
        "a2a_schedule_executions",
        ["status", "scheduled_for"],
        schema="a2a",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_a2a_schedule_executions_queue_poll",
        table_name="a2a_schedule_executions",
        schema="a2a",
    )
