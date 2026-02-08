"""Aggregated dimension statistics model for non-daily granularities."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID

from app.db.mixins.user_filter import UserFilterMixin
from app.db.models.base import SCHEMA_NAME, Base, TimestampMixin, UserOwnedMixin


class AggregatedDimensionStat(Base, UserOwnedMixin, TimestampMixin, UserFilterMixin):
    """Aggregated minutes per dimension for week/month/year buckets."""

    __tablename__ = "aggregated_dimension_stats"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "granularity",
            "timezone",
            "calendar_system",
            "first_day_of_week",
            "period_start",
            "period_end",
            "dimension_id",
            name="uq_aggregated_dim_stats_user_period_dim",
        ),
        Index(
            "ix_agg_dim_user_granularity_period",
            "user_id",
            "granularity",
            "timezone",
            "period_start",
        ),
        Index(
            "ix_agg_dim_user_period_range",
            "user_id",
            "timezone",
            "period_start",
            "period_end",
        ),
        {"schema": SCHEMA_NAME},
    )

    granularity = Column(
        Enum(
            "day",
            "week",
            "month",
            "year",
            name="aggregationgranularity",
            schema=SCHEMA_NAME,
        ),
        nullable=False,
        comment="Aggregation granularity (day/week/month/year)",
    )

    period_start = Column(
        Date,
        nullable=False,
        comment="Inclusive start date for the aggregation bucket",
    )

    period_end = Column(
        Date,
        nullable=False,
        comment="Inclusive end date for the aggregation bucket",
    )

    timezone = Column(
        String(64),
        nullable=False,
        comment="Timezone identifier used for this aggregation",
    )

    calendar_system = Column(
        String(32),
        nullable=False,
        comment="Calendar system used when deriving the bucket",
    )

    first_day_of_week = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="First day of week (1=Monday...7=Sunday) when granularity is week; 0 for non-week",
    )

    dimension_id = Column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.dimensions.id"),
        nullable=False,
        comment="Referenced dimension id",
    )

    minutes = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Total minutes aggregated for the bucket",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            "<AggregatedDimensionStat(granularity={g}, period_start={ps}, "
            "period_end={pe}, dimension_id={dim}, minutes={mins})>".format(
                g=self.granularity,
                ps=self.period_start,
                pe=self.period_end,
                dim=self.dimension_id,
                mins=self.minutes,
            )
        )
