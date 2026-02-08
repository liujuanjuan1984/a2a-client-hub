"""create note ingest jobs table

Revision ID: 1d93926ab9fb
Revises: 167eb8d8d0f6
Create Date: 2025-12-03 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '1d93926ab9fb'
down_revision = '167eb8d8d0f6'
branch_labels = None
depends_on = None


STATUS_ENUM_NAME = 'note_ingest_job_status'
SCHEMA = 'common_compass_schema'


def upgrade() -> None:
    status_enum = sa.Enum(
        'pending',
        'extracting',
        'executing',
        'succeeded',
        'failed',
        name=STATUS_ENUM_NAME,
        schema=SCHEMA,
    )

    op.create_table(
        'note_ingest_jobs',
        sa.Column('id', sa.UUID(), nullable=False, comment='Primary key (UUID v4)'),
        sa.Column('user_id', sa.UUID(), nullable=False, comment='Data owner (UUID)'),
        sa.Column('note_id', sa.UUID(), nullable=False, comment='Target note for ingestion'),
        sa.Column(
            'status',
            status_enum,
            server_default='pending',
            nullable=False,
            comment='Processing status for the ingestion job',
        ),
        sa.Column('retry_count', sa.Integer(), server_default='0', nullable=False, comment='Number of retry attempts'),
        sa.Column('available_at', sa.DateTime(timezone=True), nullable=True, comment='When the job becomes eligible for processing'),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True, comment='Timestamp of the last processing attempt'),
        sa.Column('llm_prompt_tokens', sa.Integer(), server_default='0', nullable=False, comment='Prompt tokens consumed during extraction'),
        sa.Column('llm_completion_tokens', sa.Integer(), server_default='0', nullable=False, comment='Completion tokens consumed during extraction'),
        sa.Column('llm_total_tokens', sa.Integer(), server_default='0', nullable=False, comment='Total tokens consumed during extraction'),
        sa.Column('llm_cost_usd', sa.Numeric(10, 6), nullable=True, comment='USD cost charged for extraction'),
        sa.Column('extraction_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Raw JSON emitted by the extractor'),
        sa.Column('result_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='Execution summary JSON'),
        sa.Column('error', sa.Text(), nullable=True, comment='Last error details if failed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='Job creation timestamp'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='Last update timestamp'),
        sa.ForeignKeyConstraint(['note_id'], [f'{SCHEMA}.notes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], [f'{SCHEMA}.users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema=SCHEMA,
    )
    op.create_index(op.f('ix_common_compass_schema_note_ingest_jobs_user_id'), 'note_ingest_jobs', ['user_id'], unique=False, schema=SCHEMA)
    op.create_index(op.f('ix_common_compass_schema_note_ingest_jobs_note_id'), 'note_ingest_jobs', ['note_id'], unique=False, schema=SCHEMA)
    op.create_index(op.f('ix_common_compass_schema_note_ingest_jobs_status'), 'note_ingest_jobs', ['status'], unique=False, schema=SCHEMA)


def downgrade() -> None:
    op.drop_index(op.f('ix_common_compass_schema_note_ingest_jobs_status'), table_name='note_ingest_jobs', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_note_ingest_jobs_note_id'), table_name='note_ingest_jobs', schema=SCHEMA)
    op.drop_index(op.f('ix_common_compass_schema_note_ingest_jobs_user_id'), table_name='note_ingest_jobs', schema=SCHEMA)
    op.drop_table('note_ingest_jobs', schema=SCHEMA)
    status_enum = sa.Enum(  # type: ignore[arg-type]
        'pending',
        'extracting',
        'executing',
        'succeeded',
        'failed',
        name=STATUS_ENUM_NAME,
        schema=SCHEMA,
    )
    status_enum.drop(op.get_bind(), checkfirst=True)
