"""
DailyDimensionStat SQLAlchemy model

Stores aggregated minutes per day per dimension for analytics.
"""

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class DailyDimensionStat(Base, UserOwnedMixin, TimestampMixin, UserFilterMixin):
    """Aggregated minutes spent per dimension per calendar day (UTC).

    Primary key is a composite of (stat_date, dimension_id).
    """

    __tablename__ = "daily_dimension_stats"
    __table_args__ = (
        # A row is unique for a user, given stat_date + dimension + timezone key
        UniqueConstraint(
            "user_id",
            "stat_date",
            "dimension_id",
            "timezone",
            name="uq_daily_dimension_stats_user_date_dim_timezone",
        ),
        Index("ix_daily_dim_user_date_timezone", "user_id", "stat_date", "timezone"),
        Index(
            "ix_daily_dim_user_dimension_timezone",
            "user_id",
            "dimension_id",
            "timezone",
        ),
        {"schema": SCHEMA_NAME},
    )

    # Calendar date in UTC
    stat_date = Column(
        Date, nullable=False, comment="UTC calendar date of the statistic"
    )

    # Dimension id (FK to dimensions)
    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id"),
        nullable=False,
        comment="Referenced dimension id",
    )

    # Timezone key used for the aggregation (IANA identifier)
    timezone = Column(
        String(64),
        nullable=False,
        comment="Timezone identifier used for this aggregation (IANA format)",
    )

    # Total minutes spent on this day for the dimension
    minutes = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total minutes for the day and dimension",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<DailyDimensionStat(date={self.stat_date}, dimension_id={self.dimension_id}, minutes={self.minutes})>"
