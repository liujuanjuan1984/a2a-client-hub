"""add tag category and person location tags

Revision ID: 8f2d3c4b5a61
Revises: 7a3c8d9e4f20
Create Date: 2026-01-31 10:45:00.000000

"""

from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

SCHEMA_NAME = "common_compass_schema"

# revision identifiers, used by Alembic.
revision = "8f2d3c4b5a61"
down_revision = "7a3c8d9e4f20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tags",
        sa.Column(
            "category",
            sa.String(length=50),
            nullable=False,
            server_default="general",
            comment="Tag category for semantic grouping (e.g., 'general', 'location')",
        ),
        schema=SCHEMA_NAME,
    )
    op.create_index(
        op.f("ix_common_compass_schema_tags_category"),
        "tags",
        ["category"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index("ix_tags_name_entity_type", table_name="tags", schema=SCHEMA_NAME)
    op.create_index(
        "ix_tags_name_entity_type_category",
        "tags",
        ["name", "entity_type", "category"],
        unique=False,
        schema=SCHEMA_NAME,
    )

    connection = op.get_bind()

    connection.execute(
        text(
            f"""
            UPDATE {SCHEMA_NAME}.persons
            SET location = left(trim(location), 100)
            WHERE location IS NOT NULL
              AND trim(location) <> ''
              AND length(trim(location)) > 100
        """
        )
    )

    op.alter_column(
        "persons",
        "location",
        type_=sa.String(length=100),
        existing_type=sa.String(length=200),
        nullable=True,
        schema=SCHEMA_NAME,
    )

    location_rows = connection.execute(
        text(
            f"""
            SELECT DISTINCT user_id, left(lower(trim(location)), 100) AS name
            FROM {SCHEMA_NAME}.persons
            WHERE location IS NOT NULL
              AND trim(location) <> ''
        """
        )
    ).fetchall()

    if location_rows:
        existing_rows = connection.execute(
            text(
                f"""
                SELECT user_id, name
                FROM {SCHEMA_NAME}.tags
                WHERE entity_type = 'person'
                  AND category = 'location'
                  AND deleted_at IS NULL
            """
            )
        ).fetchall()

        existing = {(row.user_id, row.name) for row in existing_rows}

        insert_stmt = text(
            f"""
            INSERT INTO {SCHEMA_NAME}.tags
                (id, user_id, name, entity_type, category, created_at, updated_at)
            VALUES
                (:id, :user_id, :name, 'person', 'location', now(), now())
        """
        )

        for row in location_rows:
            key = (row.user_id, row.name)
            if key in existing:
                continue
            connection.execute(
                insert_stmt,
                {"id": str(uuid4()), "user_id": row.user_id, "name": row.name},
            )

        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA_NAME}.tag_associations (entity_id, entity_type, tag_id)
                SELECT p.id, 'person', t.id
                FROM {SCHEMA_NAME}.persons p
                JOIN {SCHEMA_NAME}.tags t
                  ON t.user_id = p.user_id
                 AND t.name = left(lower(trim(p.location)), 100)
                 AND t.entity_type = 'person'
                 AND t.category = 'location'
                 AND t.deleted_at IS NULL
                WHERE p.location IS NOT NULL
                  AND trim(p.location) <> ''
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {SCHEMA_NAME}.tag_associations ta
                      WHERE ta.entity_id = p.id
                        AND ta.entity_type = 'person'
                        AND ta.tag_id = t.id
                  )
            """
            )
        )


def downgrade() -> None:
    op.execute(
        text(
            f"""
            DELETE FROM {SCHEMA_NAME}.tag_associations ta
            USING {SCHEMA_NAME}.tags t
            WHERE ta.tag_id = t.id
              AND t.entity_type = 'person'
              AND t.category = 'location'
        """
        )
    )
    op.execute(
        text(
            f"""
            DELETE FROM {SCHEMA_NAME}.tags
            WHERE entity_type = 'person'
              AND category = 'location'
        """
        )
    )
    op.drop_index(
        "ix_tags_name_entity_type_category", table_name="tags", schema=SCHEMA_NAME
    )
    op.create_index(
        "ix_tags_name_entity_type",
        "tags",
        ["name", "entity_type"],
        unique=False,
        schema=SCHEMA_NAME,
    )
    op.drop_index(
        op.f("ix_common_compass_schema_tags_category"),
        table_name="tags",
        schema=SCHEMA_NAME,
    )
    op.drop_column("tags", "category", schema=SCHEMA_NAME)
    op.alter_column(
        "persons",
        "location",
        type_=sa.String(length=200),
        existing_type=sa.String(length=100),
        nullable=True,
        schema=SCHEMA_NAME,
    )
