"""replace task notes with notes_count

Revision ID: 6c6b8f4b9d42
Revises: 3169578ad86b
Create Date: 2025-10-15 01:19:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6c6b8f4b9d42'
down_revision = '3169578ad86b'
branch_labels = None
depends_on = None

SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column(
            'notes_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
            comment='Number of notes associated with this task',
        ),
        schema=SCHEMA,
    )

    op.execute(
        f"""
        UPDATE {SCHEMA}.tasks AS t
        SET notes_count = COALESCE(sub.cnt, 0)
        FROM (
            SELECT
                a.target_id AS task_id,
                COUNT(*) AS cnt
            FROM {SCHEMA}.associations AS a
            WHERE a.target_model = 'Task'
              AND a.source_model = 'Note'
              AND a.link_type = 'relates_to'
              AND a.deleted_at IS NULL
            GROUP BY a.target_id
        ) AS sub
        WHERE t.id = sub.task_id
        """
    )

    op.alter_column('tasks', 'notes_count', server_default=None, schema=SCHEMA)
    op.drop_column('tasks', 'notes', schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('notes', sa.Text(), nullable=True, comment='Legacy task notes field'),
        schema=SCHEMA,
    )
    op.drop_column('tasks', 'notes_count', schema=SCHEMA)
