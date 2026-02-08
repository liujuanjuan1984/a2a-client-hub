"""Finance account data models."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
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


class FinanceAccountTree(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Tree container for finance accounts."""

    __tablename__ = "finance_account_trees"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "name",
            name="uq_finance_account_tree_user_name",
        ),
        Index(
            "ix_finance_account_trees_user_default",
            "user_id",
            "is_default",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(String(200), nullable=False)
    display_order = Column(Integer, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)

    accounts = relationship("FinanceAccount", back_populates="tree")
    snapshots = relationship("FinanceSnapshot", back_populates="tree")


class FinanceAccount(Base, TimestampMixin, UserOwnedMixin, SoftDeleteMixin):
    """Hierarchical financial account definition."""

    __tablename__ = "finance_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tree_id",
            "parent_id",
            "name",
            name="uq_finance_account_tree_parent_name",
        ),
        CheckConstraint("depth >= 0", name="ck_finance_account_depth_nonnegative"),
        Index(
            "ix_finance_accounts_user_tree_path",
            "user_id",
            "tree_id",
            "path",
            unique=True,
        ),
        Index(
            "ix_finance_accounts_tree_id",
            "tree_id",
        ),
        {"schema": SCHEMA_NAME},
    )

    name = Column(String(200), nullable=False, index=True)
    tree_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.finance_account_trees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    parent_id = Column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NAME}.finance_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    path = Column(String(1024), nullable=False, index=True)
    depth = Column(Integer, nullable=False, default=0)
    type = Column(
        String(16),
        nullable=False,
        default="asset",
        doc="Account type: asset/liability/equity/other",
    )
    nature = Column(String(32), nullable=True, doc="Account nature (demand/term/etc.)")
    currency_code = Column(String(16), nullable=False)
    interest_rate = Column(Numeric(9, 6), nullable=True)
    display_order = Column(Integer, nullable=True)
    metadata_json = Column("metadata", JSONB, nullable=True)

    tree = relationship(
        "FinanceAccountTree",
        back_populates="accounts",
    )
    parent = relationship(
        "FinanceAccount",
        remote_side="FinanceAccount.id",
        back_populates="children",
    )
    children = relationship(
        "FinanceAccount",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="FinanceAccount.display_order",
    )
    snapshot_entries = relationship(
        "FinanceSnapshotEntry",
        back_populates="account",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"FinanceAccount(id={self.id}, name={self.name!r}, path={self.path!r})"


__all__ = ["FinanceAccountTree", "FinanceAccount"]
