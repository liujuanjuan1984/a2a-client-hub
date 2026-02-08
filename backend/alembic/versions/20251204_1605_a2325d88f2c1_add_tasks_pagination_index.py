"""add tasks pagination index

Revision ID: a2325d88f2c1
Revises: 1d93926ab9fb
Create Date: 2025-12-04 16:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2325d88f2c1'
down_revision = '1d93926ab9fb'
branch_labels = None
depends_on = None

SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.create_index(
        'ix_tasks_user_vision_order_created',
        'tasks',
        ['user_id', 'vision_id', 'display_order', 'created_at'],
        unique=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_tasks_user_vision_order_created',
        table_name='tasks',
        schema=SCHEMA,
    )
