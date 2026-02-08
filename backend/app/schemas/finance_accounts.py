"""Schemas for finance account operations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.finance_common import decimal_to_str


class FinanceAccountBase(BaseModel):
    """Shared fields for finance accounts."""

    name: str = Field(..., min_length=1, max_length=200)
    parent_id: Optional[UUID] = Field(None)
    type: str = Field(
        "asset",
        description="Account type classification",
        pattern=r"^(asset|liability|equity|other)$",
    )
    nature: Optional[str] = Field(None, max_length=32)
    currency_code: str = Field(..., min_length=1, max_length=16)
    interest_rate: Optional[Decimal] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = Field(None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Account name cannot be empty")
        return text

    @field_validator("currency_code")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("interest_rate")
    @classmethod
    def validate_interest_rate(cls, value: Decimal) -> Decimal:
        if value is None:
            return None
        return value


class FinanceAccountCreate(FinanceAccountBase):
    """Payload for creating a finance account."""

    tree_id: Optional[UUID] = None


class FinanceAccountUpdate(BaseModel):
    """Payload for updating a finance account."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    parent_id: Optional[UUID] = None
    type: Optional[str] = Field(None, pattern=r"^(asset|liability|equity|other)$")
    nature: Optional[str] = Field(None, max_length=32)
    currency_code: Optional[str] = Field(None, min_length=1, max_length=16)
    interest_rate: Optional[Decimal] = None
    metadata: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = Field(None, ge=0)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("Account name cannot be empty")
        return text

    @field_validator("currency_code")
    @classmethod
    def uppercase_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value

    @field_validator("interest_rate")
    @classmethod
    def validate_interest_rate(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        if value is None:
            return None
        return value


class FinanceAccountNode(BaseModel):
    """Tree node representation of a finance account."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tree_id: UUID
    parent_id: Optional[UUID]
    name: str
    path: str
    depth: int
    type: str
    nature: Optional[str]
    currency_code: str
    interest_rate: Optional[Decimal] = None
    sort_order: Optional[int]
    metadata: Optional[Dict[str, Any]]
    latest_snapshot_id: Optional[UUID] = None
    latest_balance_raw: Optional[Decimal] = None
    latest_balance_converted: Optional[Decimal] = None
    children: List["FinanceAccountNode"] = Field(default_factory=list)

    @field_serializer("interest_rate", mode="plain")
    def serialize_interest_rate(self, value: Optional[Decimal]) -> Optional[str]:
        if value is None:
            return None
        return decimal_to_str(value) or "0"

    @field_serializer("latest_balance_raw", "latest_balance_converted", mode="plain")
    def serialize_balances(self, value: Optional[Decimal]) -> Optional[str]:
        return decimal_to_str(value)


FinanceAccountNode.model_rebuild()


class FinanceAccountTreeResponse(BaseModel):
    """Response containing the full account tree and context metadata."""

    tree_id: UUID
    accounts: List[FinanceAccountNode]
    latest_snapshot_id: Optional[UUID]
    latest_snapshot_ts: Optional[str]
    primary_currency: str


class FinanceAccountTreeCreate(BaseModel):
    """Payload for creating a finance account tree."""

    name: str = Field(..., min_length=1, max_length=200)
    is_default: Optional[bool] = False
    display_order: Optional[int] = Field(None, ge=0)


class FinanceAccountTreeUpdate(BaseModel):
    """Payload for updating a finance account tree."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_default: Optional[bool] = None
    display_order: Optional[int] = Field(None, ge=0)


class FinanceAccountTreeItem(BaseModel):
    """Tree list item for account trees."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_default: bool
    display_order: Optional[int]


__all__ = [
    "FinanceAccountCreate",
    "FinanceAccountUpdate",
    "FinanceAccountNode",
    "FinanceAccountTreeResponse",
    "FinanceAccountBase",
    "FinanceAccountTreeCreate",
    "FinanceAccountTreeUpdate",
    "FinanceAccountTreeItem",
]
