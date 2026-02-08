"""add planned event occurrence exceptions table

Revision ID: 7e2b3147811a
Revises: a2325d88f2c1
Create Date: 2025-12-29 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e2b3147811a'
down_revision = 'a2325d88f2c1'
branch_labels = None
depends_on = None


SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    op.create_table(
        'planned_event_occurrence_exceptions',
        sa.Column('id', sa.UUID(), nullable=False, comment='Primary key (UUID v4)'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='Record creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='Record last update timestamp'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='Soft delete timestamp (NULL means not deleted)'),
        sa.Column('user_id', sa.UUID(), nullable=False, comment='Data owner (UUID)'),
        sa.Column('master_event_id', sa.UUID(), nullable=False, comment='Reference to the recurring master event'),
        sa.Column('action', sa.String(length=32), nullable=False, comment='Exception action: skip, truncate, override'),
        sa.Column('instance_id', sa.UUID(), nullable=True, comment='Deterministic identifier for the specific occurrence'),
        sa.Column('instance_start', sa.DateTime(timezone=True), nullable=False, comment='Occurrence start time (UTC)'),
        sa.Column('payload', sa.JSON(), nullable=True, comment='Optional override payload (future use)'),
        sa.ForeignKeyConstraint(['user_id'], [f'{SCHEMA}.users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['master_event_id'], [f'{SCHEMA}.planned_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index(
        op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_user_id'),
        'planned_event_occurrence_exceptions',
        ['user_id'],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_master_event_id'),
        'planned_event_occurrence_exceptions',
        ['master_event_id'],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_action'),
        'planned_event_occurrence_exceptions',
        ['action'],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_instance_id'),
        'planned_event_occurrence_exceptions',
        ['instance_id'],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_instance_start'),
        'planned_event_occurrence_exceptions',
        ['instance_start'],
        unique=False,
        schema=SCHEMA,
    )
    op.create_index(
        'uq_cc_planned_event_occ_exc_master_instance',
        'planned_event_occurrence_exceptions',
        ['master_event_id', 'instance_id'],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text('instance_id IS NOT NULL'),
    )
    op.create_index(
        'uq_cc_planned_event_occ_exc_master_truncate',
        'planned_event_occurrence_exceptions',
        ['master_event_id'],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("action = 'truncate'"),
    )


def downgrade() -> None:
    op.drop_index('uq_cc_planned_event_occ_exc_master_truncate', table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index('uq_cc_planned_event_occ_exc_master_instance', table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_instance_start'), table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_instance_id'), table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_action'), table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_master_event_id'), table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_planned_event_occurrence_exceptions_user_id'), table_name='planned_event_occurrence_exceptions', schema=SCHEMA)
    op.drop_table('planned_event_occurrence_exceptions', schema=SCHEMA)
