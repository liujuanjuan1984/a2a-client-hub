"""Work recalculation job model."""

from typing import ClassVar
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.db.models.base import SCHEMA_NAME, Base
from app.utils.timezone_util import utc_now


class WorkRecalcJob(Base):
    """Background job for recomputing task effort totals and vision experience."""

    __tablename__ = "work_recalc_jobs"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_work_recalc_jobs_entity"),
        {"schema": SCHEMA_NAME},
    )

    ENTITY_TASK: ClassVar[str] = "task"
    ENTITY_VISION: ClassVar[str] = "vision"

    STATUS_PENDING: ClassVar[str] = "pending"
    STATUS_PROCESSING: ClassVar[str] = "processing"
    STATUS_DONE: ClassVar[str] = "done"
    STATUS_FAILED: ClassVar[str] = "failed"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        comment="Primary key (UUID v4)",
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Owner of the job",
    )
    entity_type = Column(
        Enum(
            ENTITY_TASK,
            ENTITY_VISION,
            name="work_recalc_entity_type",
            schema=SCHEMA_NAME,
        ),
        nullable=False,
        comment="Entity type that requires recomputation",
    )
    entity_id = Column(
        UUID(as_uuid=True),
        nullable=False,
        comment="Primary key of the entity that should be recalculated",
    )
    status = Column(
        Enum(
            STATUS_PENDING,
            STATUS_PROCESSING,
            STATUS_DONE,
            STATUS_FAILED,
            name="work_recalc_status",
            schema=SCHEMA_NAME,
        ),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
        comment="Processing status for the job",
    )
    priority = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Higher value processed first",
    )
    available_at = Column(
        DateTime(timezone=True),
        nullable=True,
        default=utc_now,
        server_default=func.now(),
        comment="Earliest time when the job becomes eligible for processing",
    )
    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of retry attempts",
    )
    reason = Column(
        String(255),
        nullable=True,
        comment="Optional reason / debug info for scheduling",
    )
    last_attempt_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last processing attempt",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
        comment="Job creation timestamp",
    )


__all__ = ["WorkRecalcJob"]
