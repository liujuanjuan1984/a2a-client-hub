"""Add structured error_code to a2a_schedule_executions.

Revision ID: r202603181130
Revises: 4b6c6e0d8a2f
Create Date: 2026-03-18 11:30:00.000000
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "r202603181130"  # pragma: allowlist secret
down_revision = "4b6c6e0d8a2f"  # pragma: allowlist secret
branch_labels = None
depends_on = None

SCHEMA_NAME = os.getenv("SCHEMA_NAME", "a2a_client_hub_schema")


def upgrade() -> None:
    op.add_column(
        "a2a_schedule_executions",
        sa.Column(
            "error_code",
            sa.String(length=96),
            nullable=True,
            comment="Structured failure code if execution did not succeed",
        ),
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_column(
        "a2a_schedule_executions",
        "error_code",
        schema=SCHEMA_NAME,
    )
