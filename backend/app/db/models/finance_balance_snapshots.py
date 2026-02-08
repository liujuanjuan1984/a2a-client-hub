"""Finance balance snapshot data models."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.models.base import (
    SCHEMA_NAME,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UserOwnedMixin,
)


class FinanceSnapshot(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Point-in-time snapshot of account balances for a user."""

    __tablename__ = "finance_snapshots"
    __table_args__ = (
        Index(
            "ix_finance_snapshots_user_tree_ts",
            "user_id",
            "tree_id",
            "snapshot_ts",
        ),
        {"schema": SCHEMA_NAME},
    )

    tree_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.finance_account_trees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    snapshot_ts = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    primary_currency = Column(String(16), nullable=False)
    note = Column(Text, nullable=True)
    created_via = Column(String(32), nullable=False, default="manual")
    summary = Column(
        JSONB,
        nullable=False,
        default=dict,
        doc="Aggregated metrics (assets/liabilities/net_worth/etc.)",
    )
    exchange_rates = Column(
        JSONB,
        nullable=True,
        doc='Optional exchange rate map, e.g. {"USD": "7.20"}',
    )

    entries = relationship(
        "FinanceSnapshotEntry",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
    tree = relationship(
        "FinanceAccountTree",
        back_populates="snapshots",
    )


class FinanceSnapshotEntry(Base, TimestampMixin, SoftDeleteMixin):
    """Per-account balance stored within a snapshot."""

    __tablename__ = "finance_snapshot_entries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "account_id",
            name="uq_finance_snapshot_entry_account",
        ),
        {"schema": SCHEMA_NAME},
    )

    snapshot_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.finance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    account_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.finance_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    balance_original = Column(Numeric(20, 8), nullable=False)
    currency_code = Column(String(16), nullable=False)
    balance_converted = Column(Numeric(20, 8), nullable=False)
    note = Column(Text, nullable=True)

    snapshot = relationship(
        "FinanceSnapshot",
        back_populates="entries",
    )
    account = relationship(
        "FinanceAccount",
        back_populates="snapshot_entries",
    )


__all__ = ["FinanceSnapshot", "FinanceSnapshotEntry"]
