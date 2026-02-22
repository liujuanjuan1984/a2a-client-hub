"""Add agent_id to shortcut

Revision ID: 1a2b3c4d5e6f
Revises: 0f2a8b8f5e11
Create Date: 2026-02-22 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = '0f2a8b8f5e11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_shortcuts', sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True, comment='If set, shortcut only applies to this specific agent'), schema='a2a_client_hub')
    op.create_index('ix_user_shortcuts_agent_id', 'user_shortcuts', ['agent_id'], unique=False, schema='a2a_client_hub')


def downgrade() -> None:
    op.drop_index('ix_user_shortcuts_agent_id', table_name='user_shortcuts', schema='a2a_client_hub')
    op.drop_column('user_shortcuts', 'agent_id', schema='a2a_client_hub')
