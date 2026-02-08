"""Finance cashflow data models."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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


class CashflowSourceTree(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Tree container for cashflow sources."""

    __tablename__ = "cashflow_source_trees"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_cashflow_source_tree_user_name",
        ),
        Index(
            "ix_cashflow_source_trees_user_default",
            "user_id",
            "is_default",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(String(200), nullable=False)
    display_order = Column(Integer, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)

    sources = relationship("CashflowSource", back_populates="tree")
    snapshots = relationship("CashflowSnapshot", back_populates="tree")


class CashflowSource(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Reusable definition of a cashflow source that can aggregate child sources."""

    __tablename__ = "cashflow_sources"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tree_id",
            "parent_id",
            "name",
            name="uq_cashflow_source_tree_parent_name",
        ),
        Index(
            "ix_cashflow_sources_user_tree_path",
            "user_id",
            "tree_id",
            "path",
            unique=True,
        ),
        Index(
            "ix_cashflow_sources_user_tree_kind",
            "user_id",
            "tree_id",
            "kind",
        ),
        Index(
            "ix_cashflow_sources_tree_id",
            "tree_id",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(String(120), nullable=False)
    tree_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_source_trees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_sources.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind = Column(String(16), nullable=False, default="regular")
    billing_cycle_type = Column(String(16), nullable=True)
    billing_cycle_interval = Column(Integer, nullable=True)
    billing_anchor_day = Column(Integer, nullable=True)
    billing_anchor_date = Column(Date, nullable=True)
    billing_post_to = Column(String(8), nullable=True)
    billing_default_amount = Column(Numeric(20, 8), nullable=True)
    billing_default_note = Column(Text, nullable=True)
    billing_requires_manual_input = Column(Boolean, nullable=False, default=False)
    currency_code = Column(
        String(16),
        nullable=False,
        default="USD",
        doc="Default currency for manual entries under this source.",
    )
    path = Column(String(1024), nullable=False, default="")
    depth = Column(Integer, nullable=False, default=0)
    display_order = Column(Integer, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)
    is_rollup = Column(
        Boolean,
        nullable=False,
        default=False,
        doc="Marks whether source amount should be computed from children.",
    )
    children_count = Column(
        Integer,
        nullable=False,
        default=0,
        doc="Cached number of direct children for quick parent checks.",
    )

    tree = relationship(
        "CashflowSourceTree",
        back_populates="sources",
    )
    parent = relationship(
        "CashflowSource",
        remote_side="CashflowSource.id",
        back_populates="children",
    )
    children = relationship(
        "CashflowSource",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="CashflowSource.display_order",
    )
    snapshot_entries = relationship(
        "CashflowSnapshotEntry",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    billing_entries = relationship(
        "CashflowBillingEntry",
        back_populates="source",
        cascade="all, delete-orphan",
    )


class CashflowSnapshot(Base, TimestampMixin, UserOwnedMixin):
    """Period-based cashflow summary."""

    __tablename__ = "cashflow_snapshots"
    __table_args__ = (
        Index(
            "ix_cashflow_snapshots_user_tree_period",
            "user_id",
            "tree_id",
            "period_start",
            "period_end",
        ),
        {"schema": SCHEMA_NAME},
    )

    tree_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_source_trees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    primary_currency = Column(String(16), nullable=False)
    total_income = Column(Numeric(20, 8), nullable=False)
    total_expense = Column(Numeric(20, 8), nullable=False)
    net_cashflow = Column(Numeric(20, 8), nullable=False)
    total_positive = Column(
        Numeric(20, 8),
        nullable=False,
        default=0,
        doc="Sum of positive cashflow amounts within the snapshot.",
    )
    total_negative = Column(
        Numeric(20, 8),
        nullable=False,
        default=0,
        doc="Sum of negative cashflow amounts within the snapshot.",
    )
    exchange_rates = Column(
        JSONB,
        nullable=True,
        doc='Optional exchange rate map, e.g. {"USD": "7.20"}',
    )
    snapshot_ts = Column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when exchange rate snapshot is captured.",
    )
    summary = Column(
        JSONB,
        nullable=True,
        default=dict,
        doc="Optional breakdown data e.g. top sources",
    )
    note = Column(Text, nullable=True)

    entries = relationship(
        "CashflowSnapshotEntry",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    tree = relationship(
        "CashflowSourceTree",
        back_populates="snapshots",
    )


class CashflowSnapshotEntry(Base, TimestampMixin, SoftDeleteMixin):
    """Amount per source captured within a cashflow snapshot."""

    __tablename__ = "cashflow_snapshot_entries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_id",
            name="uq_cashflow_snapshot_entry_source",
        ),
        {"schema": SCHEMA_NAME},
    )

    snapshot_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount = Column(Numeric(20, 8), nullable=False)
    currency_code = Column(String(16), nullable=False)
    note = Column(Text, nullable=True)
    is_auto_generated = Column(
        Boolean,
        nullable=False,
        default=False,
        doc="Indicates entry resulted from automated billing or rollup.",
    )

    snapshot = relationship(
        "CashflowSnapshot",
        back_populates="entries",
    )
    source = relationship(
        "CashflowSource",
        back_populates="snapshot_entries",
    )


class CashflowBillingEntry(Base, TimestampMixin, UserOwnedMixin):
    """Individual billing cycle entry aligned with configured cycles."""

    __tablename__ = "cashflow_billing_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_id",
            "cycle_start",
            "cycle_end",
            name="uq_cashflow_billing_cycle",
        ),
        Index(
            "ix_cashflow_billing_entries_source_month",
            "source_id",
            "posted_month",
        ),
        {"schema": SCHEMA_NAME},
    )

    source_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.cashflow_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    cycle_start = Column(Date, nullable=False)
    cycle_end = Column(Date, nullable=False)
    posted_month = Column(Date, nullable=False, doc="First day of natural month")
    amount = Column(Numeric(20, 8), nullable=False)
    note = Column(Text, nullable=True)
    auto_generated = Column(Boolean, nullable=False, default=False)

    source = relationship(
        "CashflowSource",
        back_populates="billing_entries",
    )


__all__ = [
    "CashflowSourceTree",
    "CashflowSource",
    "CashflowSnapshot",
    "CashflowSnapshotEntry",
    "CashflowBillingEntry",
]
