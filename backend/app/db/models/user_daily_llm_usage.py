"""Daily user LLM token usage table model."""

from datetime import date

from sqlalchemy import Column, Date, Integer, UniqueConstraint

from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class UserDailyLlmUsage(Base, TimestampMixin, UserOwnedMixin):
    """LLM token usage records aggregated by user and UTC natural day."""

    __tablename__ = "user_daily_llm_usage"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "usage_date",
            name="uq_user_daily_llm_usage_user_date",
        ),
        {"schema": SCHEMA_NAME},
    )

    usage_date = Column(
        Date,
        nullable=False,
        comment="UTC natural date when LLM consumption occurred",
    )
    tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Cumulative total_tokens for the day",
    )
    request_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of LLM requests triggered on the day",
    )
    system_tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Tokens billed to system-provided credentials",
    )
    system_request_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Request count billed to system-provided credentials",
    )
    user_tokens_total = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Tokens billed to BYOT credentials",
    )
    user_request_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Request count billed to BYOT credentials",
    )
    max_tokens_snapshot = Column(
        Integer,
        nullable=True,
        comment="Records max_tokens configuration at request time for traceability",
    )

    def ensure_usage_date(self) -> date:
        """Convenient method to get date object in the call chain."""

        if isinstance(self.usage_date, date):
            return self.usage_date
        raise ValueError("usage_date has not been assigned")


__all__ = ["UserDailyLlmUsage"]
