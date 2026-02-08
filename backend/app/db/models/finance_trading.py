"""Trading plan domain models."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)

NUMERIC_30_12 = Numeric(30, 12)


class TradingPlan(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Top-level trading plan definition."""

    __tablename__ = "trading_plans"
    __table_args__ = (
        Index(
            "ix_trading_plans_user_period",
            "user_id",
            "period_start",
            "period_end",
        ),
        Index(
            "ix_trading_plans_user_status",
            "user_id",
            "status",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name="ck_trading_plans_valid_status",
        ),
        CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end >= period_start",
            name="ck_trading_plans_period_range",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(String(200), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    target_roi = Column(Numeric(9, 4), nullable=True)
    note = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="draft")
    rate_snapshot_ts = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    rate_snapshot_currency = Column(String(16), nullable=True)
    rate_snapshot_rates = Column(JSONB, nullable=True)

    instruments = relationship(
        "TradingInstrument",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    entries = relationship(
        "TradingEntry",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    metrics = relationship(
        "TradingInstrumentMetric",
        back_populates="plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TradingInstrument(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Tradable instrument scoped to a trading plan."""

    __tablename__ = "trading_instruments"
    __table_args__ = (
        Index(
            "ix_trading_instruments_user_plan",
            "user_id",
            "plan_id",
        ),
        Index(
            "ix_trading_instruments_plan_symbol",
            "plan_id",
            "symbol",
        ),
        Index(
            "uq_trading_instruments_plan_symbol_active",
            "plan_id",
            "symbol",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": SCHEMA_NAME},
    )

    plan_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol = Column(String(64), nullable=False)
    base_asset = Column(String(32), nullable=False)
    quote_asset = Column(String(32), nullable=False)
    exchange = Column(String(64), nullable=True)
    strategy_tag = Column(String(64), nullable=True)
    note = Column(Text, nullable=True)

    plan = relationship("TradingPlan", back_populates="instruments")
    entries = relationship(
        "TradingEntry",
        back_populates="instrument",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    metrics = relationship(
        "TradingInstrumentMetric",
        back_populates="instrument",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TradingEntry(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Individual trade execution record."""

    __tablename__ = "trading_entries"
    __table_args__ = (
        Index(
            "ix_trading_entries_user_plan_time",
            "user_id",
            "plan_id",
            "trade_time",
        ),
        Index(
            "ix_trading_entries_instrument_time",
            "instrument_id",
            "trade_time",
        ),
        CheckConstraint(
            "direction IN ('buy', 'sell', 'transfer')",
            name="ck_trading_entries_direction",
        ),
        CheckConstraint(
            "source IN ('manual', 'import')",
            name="ck_trading_entries_source",
        ),
        {"schema": SCHEMA_NAME},
    )

    plan_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    instrument_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_instruments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade_time = Column(DateTime(timezone=True), nullable=False)
    direction = Column(String(16), nullable=False)
    base_delta = Column(NUMERIC_30_12, nullable=False)
    quote_delta = Column(NUMERIC_30_12, nullable=False)
    price = Column(NUMERIC_30_12, nullable=True)
    fee_asset = Column(String(32), nullable=True)
    fee_amount = Column(NUMERIC_30_12, nullable=True)
    source = Column(String(16), nullable=False, default="manual")
    note = Column(Text, nullable=True)

    plan = relationship("TradingPlan", back_populates="entries")
    instrument = relationship("TradingInstrument", back_populates="entries")


class TradingInstrumentMetric(Base, TimestampMixin, UserOwnedMixin):
    """Cached aggregates per plan and instrument."""

    __tablename__ = "trading_instrument_metrics"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "instrument_id",
            name="uq_trading_instrument_metrics_fk",
        ),
        Index(
            "ix_trading_instrument_metrics_plan",
            "plan_id",
            "instrument_id",
        ),
        {"schema": SCHEMA_NAME},
    )

    plan_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    instrument_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_instruments.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_base_in = Column(NUMERIC_30_12, nullable=False, default=0)
    total_base_out = Column(NUMERIC_30_12, nullable=False, default=0)
    net_position = Column(NUMERIC_30_12, nullable=False, default=0)
    avg_entry_price = Column(NUMERIC_30_12, nullable=True)
    realized_pnl = Column(NUMERIC_30_12, nullable=False, default=0)
    unrealized_pnl = Column(NUMERIC_30_12, nullable=False, default=0)

    plan = relationship("TradingPlan", back_populates="metrics")
    instrument = relationship("TradingInstrument", back_populates="metrics")


class ExchangeRate(Base, TimestampMixin):
    """Historical exchange rate record supporting user overrides."""

    __tablename__ = "exchange_rates"
    __table_args__ = (
        Index(
            "ix_exchange_rates_pair_time",
            "base_asset",
            "quote_asset",
            "captured_at",
        ),
        Index(
            "ix_exchange_rates_source",
            "source",
        ),
        {"schema": SCHEMA_NAME},
    )

    user_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    plan_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.trading_plans.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    base_asset = Column(String(32), nullable=False)
    quote_asset = Column(String(32), nullable=False)
    rate = Column(NUMERIC_30_12, nullable=False)
    source = Column(String(64), nullable=False, default="manual")
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)


__all__ = [
    "TradingPlan",
    "TradingInstrument",
    "TradingEntry",
    "TradingInstrumentMetric",
    "ExchangeRate",
]
