"""add a2a proxy allowlist table (#313)

Revision ID: ed8708329a6f
Revises: r202602241900
Create Date: 2026-02-26 02:31:03.764141

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.models.base import SCHEMA_NAME


# revision identifiers, used by Alembic.
revision: str = 'ed8708329a6f'
down_revision: Union[str, None] = 'r202602241900'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'a2a_proxy_allowlist',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, comment='Primary key (UUID v4)'),
        sa.Column('host_pattern', sa.String(length=255), nullable=False, comment='The host pattern allowed (e.g., example.com, *.openai.com)'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, comment='Whether this allowlist entry is active'),
        sa.Column('remark', sa.Text(), nullable=True, comment='Remark or reason for this allowlist entry'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment='Record creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment='Record last update timestamp'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_a2a_proxy_allowlist')),
        sa.UniqueConstraint('host_pattern', name=op.f('uq_a2a_proxy_allowlist_host_pattern')),
        schema=SCHEMA_NAME,
        comment='Allowlist entry for A2A proxy hosts.'
    )
    op.create_index(op.f('ix_a2a_proxy_allowlist_host_pattern'), 'a2a_proxy_allowlist', ['host_pattern'], unique=True, schema=SCHEMA_NAME)
    op.create_index(op.f('ix_a2a_proxy_allowlist_is_enabled'), 'a2a_proxy_allowlist', ['is_enabled'], unique=False, schema=SCHEMA_NAME)


def downgrade() -> None:
    op.drop_index(op.f('ix_a2a_proxy_allowlist_is_enabled'), table_name='a2a_proxy_allowlist', schema=SCHEMA_NAME)
    op.drop_index(op.f('ix_a2a_proxy_allowlist_host_pattern'), table_name='a2a_proxy_allowlist', schema=SCHEMA_NAME)
    op.drop_table('a2a_proxy_allowlist', schema=SCHEMA_NAME)
