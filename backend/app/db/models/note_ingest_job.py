"""Note ingest job SQLAlchemy model."""

from __future__ import annotations

from decimal import Decimal
from typing import ClassVar, Optional

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin
from app.utils.timezone_util import utc_now


class NoteIngestJob(Base, UserOwnedMixin, TimestampMixin):
    """Background job metadata for automatic note ingestion."""

    __tablename__ = "note_ingest_jobs"
    __table_args__ = ({"schema": SCHEMA_NAME},)

    STATUS_PENDING: ClassVar[str] = "pending"
    STATUS_EXTRACTING: ClassVar[str] = "extracting"
    STATUS_EXECUTING: ClassVar[str] = "executing"
    STATUS_SUCCEEDED: ClassVar[str] = "succeeded"
    STATUS_FAILED: ClassVar[str] = "failed"

    STATUS_CHOICES: ClassVar[tuple[str, ...]] = (
        STATUS_PENDING,
        STATUS_EXTRACTING,
        STATUS_EXECUTING,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
    )

    note_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Target note for ingestion",
    )
    status = Column(
        Enum(*STATUS_CHOICES, name="note_ingest_job_status", schema=SCHEMA_NAME),
        nullable=False,
        default=STATUS_PENDING,
        server_default=STATUS_PENDING,
        comment="Processing status for the ingestion job",
    )
    retry_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of retry attempts",
    )
    available_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the job becomes eligible for processing",
    )
    last_attempt_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of the last processing attempt",
    )
    llm_prompt_tokens = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Prompt tokens consumed during extraction",
    )
    llm_completion_tokens = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Completion tokens consumed during extraction",
    )
    llm_total_tokens = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Total tokens consumed during extraction",
    )
    llm_cost_usd = Column(
        Numeric(10, 6),
        nullable=True,
        comment="USD cost charged for the extraction run",
    )
    extraction_payload = Column(
        JSONB,
        nullable=True,
        comment="Raw JSON payload produced by the LLM extractor",
    )
    result_payload = Column(
        JSONB,
        nullable=True,
        comment="Execution summary JSON for downstream entity operations",
    )
    error = Column(
        Text,
        nullable=True,
        comment="Last error message (if any)",
    )

    def touch_attempt(self) -> None:
        """Update bookkeeping fields when the job is attempted."""

        now = utc_now()
        self.last_attempt_at = now
        if self.available_at is None or self.available_at < now:
            self.available_at = now

    def record_llm_usage(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: Optional[Decimal],
    ) -> None:
        """Persist LLM usage numbers for reporting purposes."""

        self.llm_prompt_tokens = max(prompt_tokens, 0)
        self.llm_completion_tokens = max(completion_tokens, 0)
        self.llm_total_tokens = max(total_tokens, 0)
        self.llm_cost_usd = cost_usd


__all__ = ["NoteIngestJob"]
