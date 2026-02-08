"""Daily review run persistence model."""

from __future__ import annotations

from sqlalchemy import Column, Date, Index, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class DailyReviewRun(Base, TimestampMixin, UserOwnedMixin):
    """Record execution status for daily review workflows."""

    __tablename__ = "daily_review_runs"
    __table_args__ = (
        Index(
            "ix_daily_review_runs_user_date",
            "user_id",
            "target_date",
            unique=False,
            postgresql_using="btree",
        ),
        {"schema": SCHEMA_NAME},
    )

    target_date = Column(Date, nullable=False, comment="the date of the daily review")
    status = Column(
        String(32), nullable=False, comment="the status of the daily review"
    )
    trigger_source = Column(
        String(32), nullable=False, comment="the source of the daily review"
    )
    input_box_name = Column(
        String(255), nullable=True, comment="the name of the daily review input CardBox"
    )
    output_box_name = Column(
        String(255),
        nullable=True,
        comment="the name of the daily review output CardBox",
    )
    error_message = Column(
        String(1024), nullable=True, comment="the error message of the daily review"
    )
    extra = Column(
        JSONB, nullable=True, comment="the extra information of the daily review"
    )


__all__ = ["DailyReviewRun"]
