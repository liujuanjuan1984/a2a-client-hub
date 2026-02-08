"""Schemas for finance balance snapshots and exchange rates."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.finance_common import EIGHT_PLACES, decimal_to_str
from app.schemas.pagination import ListResponse, Pagination


class BalanceSnapshotAccountInput(BaseModel):
    """Account entry included when creating a balance snapshot."""

    model_config = ConfigDict(populate_by_name=True)

    account_id: UUID = Field(..., alias="id")
    balance: Decimal
    note: Optional[str] = None

    @field_validator("balance")
    @classmethod
    def validate_balance(cls, value: Decimal) -> Decimal:
        return value.quantize(EIGHT_PLACES)


class BalanceSnapshotExchangeRateInput(BaseModel):
    """User-provided exchange rate input."""

    quote_currency: str = Field(..., min_length=1, max_length=16)
    rate: Decimal = Field(..., gt=Decimal("0"))

    @field_validator("quote_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("rate")
    @classmethod
    def enforce_precision(cls, value: Decimal) -> Decimal:
        return value.quantize(EIGHT_PLACES)


class BalanceSnapshotCreateRequest(BaseModel):
    """Payload for creating a balance snapshot."""

    primary_currency: Optional[str] = Field(None, min_length=1, max_length=16)
    tree_id: Optional[UUID] = None
    accounts: List[BalanceSnapshotAccountInput]
    exchange_rates: List[BalanceSnapshotExchangeRateInput] = Field(default_factory=list)
    note: Optional[str] = None
    snapshot_ts: Optional[datetime] = None

    @field_validator("primary_currency")
    @classmethod
    def uppercase_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value

    @field_validator("snapshot_ts")
    @classmethod
    def normalize_snapshot_ts(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value


class BalanceSnapshotUpdateRequest(BalanceSnapshotCreateRequest):
    """Payload for updating an existing balance snapshot."""


class SnapshotMetricResponse(BaseModel):
    """Metrics associated with a balance snapshot."""

    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    asset_breakdown: Optional[Dict[str, Decimal]] = None
    currency_breakdown: Optional[Dict[str, Decimal]] = None

    @field_serializer(
        "total_assets",
        "total_liabilities",
        "net_worth",
        mode="plain",
    )
    def serialize_totals(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"

    @field_serializer("asset_breakdown", "currency_breakdown", mode="plain")
    def serialize_breakdowns(
        self, value: Optional[Dict[str, Decimal]]
    ) -> Optional[Dict[str, str]]:
        if value is None:
            return None
        return {k: decimal_to_str(v) or "0" for k, v in value.items()}


class ExchangeRateSnapshotResponse(BaseModel):
    """Exchange rate record in a snapshot."""

    id: str
    quote_currency: str
    rate: Decimal

    @field_serializer("rate", mode="plain")
    def serialize_rate(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class AccountSnapshotResponse(BaseModel):
    """Account-specific values within a snapshot."""

    account_id: UUID
    account_name: str
    type: str
    currency_code: str
    balance_raw: Decimal
    balance_converted: Decimal
    path: str
    depth: int
    note: Optional[str] = None

    @field_serializer(
        "balance_raw",
        "balance_converted",
        mode="plain",
    )
    def serialize_decimals(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class BalanceSnapshotSummaryResponse(BaseModel):
    """Summary row for balance snapshot listings."""

    id: UUID
    snapshot_ts: str
    primary_currency: str
    tree_id: UUID
    note: Optional[str]
    metrics: SnapshotMetricResponse


class BalanceSnapshotPagination(Pagination):
    """Pagination metadata for balance snapshot lists."""


class BalanceSnapshotListMeta(BaseModel):
    """Additional list metadata for balance snapshot listings."""

    tree_id: Optional[UUID] = None


class BalanceSnapshotListResponse(
    ListResponse[BalanceSnapshotSummaryResponse, BalanceSnapshotListMeta]
):
    """Schema for balance snapshot list response."""

    items: List[BalanceSnapshotSummaryResponse]
    pagination: BalanceSnapshotPagination
    meta: BalanceSnapshotListMeta


class BalanceSnapshotDetailResponse(BaseModel):
    """Detailed snapshot payload including per-account data."""

    id: UUID
    snapshot_ts: str
    primary_currency: str
    tree_id: UUID
    note: Optional[str]
    metrics: SnapshotMetricResponse
    accounts: List[AccountSnapshotResponse]
    exchange_rates: List[ExchangeRateSnapshotResponse]


class BalanceSnapshotAccountChange(BaseModel):
    """Per-account delta between two snapshots."""

    account_id: UUID
    account_name: str
    currency_code: str
    type: str
    previous_balance: Decimal
    current_balance: Decimal
    delta: Decimal
    delta_percent: Optional[Decimal]

    @field_serializer(
        "previous_balance",
        "current_balance",
        "delta",
        "delta_percent",
        mode="plain",
    )
    def serialize_decimals(self, value: Optional[Decimal]) -> Optional[str]:
        return decimal_to_str(value) if value is not None else None


class BalanceSnapshotComparisonResponse(BaseModel):
    """Comparison payload between two snapshots."""

    base_snapshot_id: UUID
    compare_snapshot_id: UUID
    base_snapshot_ts: str
    compare_snapshot_ts: str
    delta_net_worth: Decimal
    base_metrics: SnapshotMetricResponse
    compare_metrics: SnapshotMetricResponse
    account_changes: List[BalanceSnapshotAccountChange]

    @field_serializer("delta_net_worth", mode="plain")
    def serialize_delta_net_worth(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class LatestExchangeRateResponse(BaseModel):
    """Response for latest exchange rates lookup."""

    snapshot_id: Optional[UUID]
    snapshot_ts: Optional[str]
    base_currency: str
    rates: Dict[str, Decimal]
    scope: Literal["snapshot", "source"] = "snapshot"

    @field_serializer("rates", mode="plain")
    def serialize_rates(self, value: Dict[str, Decimal]) -> Dict[str, str]:
        return {
            currency: decimal_to_str(rate) or "0" for currency, rate in value.items()
        }


__all__ = [
    "BalanceSnapshotAccountInput",
    "BalanceSnapshotExchangeRateInput",
    "BalanceSnapshotCreateRequest",
    "BalanceSnapshotUpdateRequest",
    "SnapshotMetricResponse",
    "ExchangeRateSnapshotResponse",
    "AccountSnapshotResponse",
    "BalanceSnapshotSummaryResponse",
    "BalanceSnapshotListResponse",
    "BalanceSnapshotDetailResponse",
    "BalanceSnapshotAccountChange",
    "BalanceSnapshotComparisonResponse",
    "LatestExchangeRateResponse",
]
