"""quick_template_persons

Revision ID: c8d1e9c3c2fb
Revises: a216ede0bc21
Create Date: 2025-10-20 11:20:00.000000

"""
from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c8d1e9c3c2fb"
down_revision = "a216ede0bc21"
branch_labels = None
depends_on = None

SCHEMA = "common_compass_schema"
LINK_TYPE = "quick_template_involves"
SOURCE_MODEL = "ActualEventQuickTemplate"
TARGET_MODEL = "Person"


def upgrade() -> None:
    conn = op.get_bind()

    templates = conn.execute(
        sa.text(
            f"""
            SELECT id, user_id, person_id
            FROM {SCHEMA}.actual_event_quick_templates
            WHERE person_id IS NOT NULL
            """
        )
    ).mappings()

    for row in templates:
        conn.execute(
            sa.text(
                f"""
                INSERT INTO {SCHEMA}.associations
                    (id, created_at, updated_at, user_id,
                     source_model, source_id, target_model, target_id, link_type)
                VALUES
                    (:id, now(), now(), :user_id,
                     :source_model, :source_id, :target_model, :target_id, :link_type)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": str(uuid4()),
                "user_id": row["user_id"],
                "source_model": SOURCE_MODEL,
                "source_id": row["id"],
                "target_model": TARGET_MODEL,
                "target_id": row["person_id"],
                "link_type": LINK_TYPE,
            },
        )

    op.drop_index(
        "ix_common_compass_schema_actual_event_quick_templates_person_id",
        table_name="actual_event_quick_templates",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "actual_event_quick_templates_person_id_fkey",
        "actual_event_quick_templates",
        type_="foreignkey",
        schema=SCHEMA,
    )
    op.drop_column("actual_event_quick_templates", "person_id", schema=SCHEMA)


def downgrade() -> None:
    op.add_column(
        "actual_event_quick_templates",
        sa.Column(
            "person_id",
            sa.UUID(),
            nullable=True,
            comment="Optional related person identifier",
        ),
        schema=SCHEMA,
    )
    op.create_foreign_key(
        "actual_event_quick_templates_person_id_fkey",
        "actual_event_quick_templates",
        "persons",
        ["person_id"],
        ["id"],
        source_schema=SCHEMA,
        referent_schema=SCHEMA,
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_common_compass_schema_actual_event_quick_templates_person_id",
        "actual_event_quick_templates",
        ["person_id"],
        schema=SCHEMA,
    )

    conn = op.get_bind()
    mappings = conn.execute(
        sa.text(
            f"""
            SELECT source_id, MIN(target_id) AS person_id
            FROM {SCHEMA}.associations
            WHERE source_model = :source_model
              AND link_type = :link_type
            GROUP BY source_id
            """
        ),
        {"source_model": SOURCE_MODEL, "link_type": LINK_TYPE},
    ).mappings()

    for row in mappings:
        conn.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA}.actual_event_quick_templates
                SET person_id = :person_id
                WHERE id = :template_id
                """
            ),
            {"person_id": row["person_id"], "template_id": row["source_id"]},
        )

    conn.execute(
        sa.text(
            f"""
            DELETE FROM {SCHEMA}.associations
            WHERE source_model = :source_model
              AND link_type = :link_type
            """
        ),
        {"source_model": SOURCE_MODEL, "link_type": LINK_TYPE},
    )
