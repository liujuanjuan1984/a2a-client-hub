"""make dimension names unique per user

Revision ID: f1d9e4d2add5
Revises: 6c6b8f4b9d42
Create Date: 2025-10-17 15:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f1d9e4d2add5"
down_revision = "34862baa9b20"
branch_labels = None
depends_on = None

SCHEMA = "common_compass_schema"


def upgrade() -> None:
    op.drop_index(
        "ix_common_compass_schema_dimensions_name",
        table_name="dimensions",
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_common_compass_schema_dimensions_user_name",
        "dimensions",
        ["user_id", "name"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_common_compass_schema_dimensions_user_name",
        "dimensions",
        type_="unique",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_common_compass_schema_dimensions_name",
        "dimensions",
        ["name"],
        unique=True,
        schema=SCHEMA,
    )
