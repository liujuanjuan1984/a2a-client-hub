"""Schemas for finance cashflow sources and snapshots."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.finance_common import EIGHT_PLACES, decimal_to_str
from app.schemas.pagination import ListResponse, Pagination


class CashflowSourceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    parent_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = Field(None, ge=0)
    kind: Literal["regular", "billing"] = "regular"
    currency_code: str = Field("USD", min_length=1, max_length=16)
    billing_cycle_type: Optional[Literal["day", "week", "month", "year"]] = None
    billing_cycle_interval: Optional[int] = Field(None, ge=1, le=365)
    billing_anchor_day: Optional[int] = Field(None, ge=1, le=31)
    billing_anchor_date: Optional[date] = None
    billing_post_to: Optional[Literal["start", "end"]] = "end"
    billing_default_amount: Optional[Decimal] = None
    billing_default_note: Optional[str] = Field(None, max_length=500)
    billing_requires_manual_input: bool = False

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_billing(self) -> "CashflowSourceBase":
        if self.kind == "regular":
            self.billing_cycle_type = None
            self.billing_cycle_interval = None
            self.billing_anchor_day = None
            self.billing_anchor_date = None
            self.billing_post_to = "end"
            self.billing_default_amount = None
            self.billing_default_note = None
            self.billing_requires_manual_input = False
            return self

        # Billing-specific validation
        if not self.billing_cycle_type:
            raise ValueError("Billing source must specify billing_cycle_type")
        if self.billing_cycle_interval is None:
            self.billing_cycle_interval = 1
        if self.billing_cycle_interval <= 0:
            raise ValueError("billing_cycle_interval must be greater than 0")

        if not self.billing_anchor_date:
            raise ValueError("Billing source must provide billing_anchor_date")

        if self.billing_cycle_type in {"month", "year"}:
            anchor_day = self.billing_anchor_day or self.billing_anchor_date.day
            if not 1 <= anchor_day <= 28:
                raise ValueError("billing_anchor_day must be between 1 and 28")
            self.billing_anchor_day = anchor_day
        else:
            self.billing_anchor_day = None

        if self.billing_post_to not in {"start", "end"}:
            self.billing_post_to = "end"

        if not self.billing_requires_manual_input:
            if self.billing_default_amount is None:
                raise ValueError(
                    "Fixed-amount billing source must provide billing_default_amount"
                )
            self.billing_default_amount = self.billing_default_amount.quantize(
                EIGHT_PLACES
            )
        else:
            if self.billing_default_amount is not None:
                self.billing_default_amount = self.billing_default_amount.quantize(
                    EIGHT_PLACES
                )

        if self.billing_default_note is not None:
            note = self.billing_default_note.strip()
            self.billing_default_note = note or None

        return self


class CashflowSourceCreate(CashflowSourceBase):
    tree_id: Optional[UUID] = None


class CashflowSourceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    parent_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None
    sort_order: Optional[int] = Field(None, ge=0)
    kind: Optional[Literal["regular", "billing"]] = None
    currency_code: Optional[str] = Field(None, min_length=1, max_length=16)
    billing_cycle_type: Optional[Literal["day", "week", "month", "year"]] = None
    billing_cycle_interval: Optional[int] = Field(None, ge=1, le=365)
    billing_anchor_day: Optional[int] = Field(None, ge=1, le=31)
    billing_anchor_date: Optional[date] = None
    billing_post_to: Optional[Literal["start", "end"]] = None
    billing_default_amount: Optional[Decimal] = None
    billing_default_note: Optional[str] = Field(None, max_length=500)
    billing_requires_manual_input: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @field_validator("currency_code")
    @classmethod
    def normalize_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value

    @model_validator(mode="after")
    def validate_billing(self) -> "CashflowSourceUpdate":
        kind = self.kind
        if kind is None and not any(
            field
            for field in (
                self.billing_cycle_type,
                self.billing_cycle_interval,
                self.billing_anchor_day,
                self.billing_anchor_date,
                self.billing_post_to,
                self.billing_default_amount,
                self.billing_default_note,
                self.billing_requires_manual_input,
            )
        ):
            return self

        # Determine effective kind
        effective_kind = kind or "billing"
        if effective_kind not in {"regular", "billing"}:
            raise ValueError("kind must be either regular or billing")

        if effective_kind == "regular":
            self.billing_cycle_type = None
            self.billing_cycle_interval = None
            self.billing_anchor_day = None
            self.billing_anchor_date = None
            self.billing_post_to = None
            self.billing_default_amount = None
            self.billing_default_note = None
            self.billing_requires_manual_input = None
            return self

        if not self.billing_cycle_type:
            raise ValueError("Billing source must specify billing_cycle_type")
        if self.billing_cycle_interval is not None and self.billing_cycle_interval <= 0:
            raise ValueError("billing_cycle_interval must be greater than 0")
        if self.billing_anchor_date is None:
            raise ValueError("Billing source must provide billing_anchor_date")

        if self.billing_cycle_type in {"month", "year"}:
            anchor_day = self.billing_anchor_day or self.billing_anchor_date.day
            if not 1 <= anchor_day <= 28:
                raise ValueError("billing_anchor_day must be between 1 and 28")
            self.billing_anchor_day = anchor_day
        else:
            self.billing_anchor_day = None

        if self.billing_post_to is not None and self.billing_post_to not in {
            "start",
            "end",
        }:
            raise ValueError("billing_post_to must be either 'start' or 'end'")

        requires_manual = self.billing_requires_manual_input
        if requires_manual is False:
            if self.billing_default_amount is None:
                raise ValueError(
                    "Fixed-amount billing source must provide billing_default_amount"
                )
            self.billing_default_amount = self.billing_default_amount.quantize(
                EIGHT_PLACES
            )
        elif self.billing_default_amount is not None:
            self.billing_default_amount = self.billing_default_amount.quantize(
                EIGHT_PLACES
            )

        if self.billing_default_note is not None:
            note = self.billing_default_note.strip()
            self.billing_default_note = note or None

        return self


class CashflowSourceNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tree_id: UUID
    parent_id: Optional[UUID]
    name: str
    path: str
    depth: int
    sort_order: Optional[int]
    metadata: Optional[Dict[str, Any]]
    kind: str = "regular"
    is_rollup: bool = False
    children_count: int = 0
    currency_code: str = "USD"
    billing_cycle_type: Optional[str] = None
    billing_cycle_interval: Optional[int] = None
    billing_anchor_day: Optional[int] = None
    billing_anchor_date: Optional[date] = None
    billing_post_to: Optional[str] = None
    billing_default_amount: Optional[Decimal] = None
    billing_default_note: Optional[str] = None
    billing_requires_manual_input: bool = False
    aggregated_amount: Optional[Decimal] = None
    children: List["CashflowSourceNode"] = Field(default_factory=list)

    @field_serializer("billing_default_amount", mode="plain")
    def serialize_default_amount(self, value: Optional[Decimal]) -> Optional[str]:
        return decimal_to_str(value) if value is not None else None

    @field_serializer("aggregated_amount", mode="plain")
    def serialize_aggregated_amount(self, value: Optional[Decimal]) -> Optional[str]:
        return decimal_to_str(value) if value is not None else None


CashflowSourceNode.model_rebuild()


class CashflowSourceTreeResponse(BaseModel):
    sources: List[CashflowSourceNode]


class CashflowSourceTreeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    is_default: Optional[bool] = False
    display_order: Optional[int] = Field(None, ge=0)


class CashflowSourceTreeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    is_default: Optional[bool] = None
    display_order: Optional[int] = Field(None, ge=0)


class CashflowSourceTreeItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    is_default: bool
    display_order: Optional[int]


class CashflowSnapshotExchangeRateInput(BaseModel):
    quote_currency: str = Field(..., min_length=1, max_length=16)
    rate: Decimal = Field(..., gt=Decimal("0"))

    @field_validator("quote_currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.strip().upper()


class CashflowSnapshotExchangeRateResponse(BaseModel):
    quote_currency: str
    rate: Decimal

    @field_serializer("rate", mode="plain")
    def serialize_rate(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class CashflowSnapshotEntryInput(BaseModel):
    source_id: UUID = Field(..., alias="id")
    amount: Decimal
    currency_code: Optional[str] = Field(None, min_length=1, max_length=16)
    note: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        return value.quantize(EIGHT_PLACES)

    @field_validator("currency_code")
    @classmethod
    def uppercase_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value


class CashflowSnapshotCreateRequest(BaseModel):
    primary_currency: Optional[str] = Field(None, min_length=1, max_length=16)
    tree_id: Optional[UUID] = None
    period_start: datetime
    period_end: datetime
    entries: List[CashflowSnapshotEntryInput]
    exchange_rates: List[CashflowSnapshotExchangeRateInput] = Field(
        default_factory=list
    )
    note: Optional[str] = None

    @field_validator("primary_currency")
    @classmethod
    def uppercase_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value


class CashflowSnapshotUpdateRequest(BaseModel):
    period_start: datetime
    period_end: datetime
    entries: List[CashflowSnapshotEntryInput]
    note: Optional[str] = None
    primary_currency: Optional[str] = Field(None, min_length=1, max_length=16)
    tree_id: Optional[UUID] = None
    exchange_rates: List[CashflowSnapshotExchangeRateInput] = Field(
        default_factory=list
    )

    @field_validator("primary_currency")
    @classmethod
    def uppercase_currency(cls, value: Optional[str]) -> Optional[str]:
        return value.strip().upper() if value else value


class CashflowSnapshotEntryResponse(BaseModel):
    source_id: UUID
    source_name: str
    amount: Decimal
    currency_code: str
    note: Optional[str] = None
    is_auto_generated: bool = False

    @field_serializer("amount", mode="plain")
    def serialize_amount(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class CashflowSnapshotSummaryResponse(BaseModel):
    id: UUID
    period_start: str
    period_end: str
    primary_currency: str
    tree_id: UUID
    snapshot_ts: Optional[str] = None
    total_income: Decimal
    total_expense: Decimal
    total_positive: Decimal
    total_negative: Decimal
    net_cashflow: Decimal
    summary: Optional[Dict[str, Any]] = None
    note: Optional[str]

    @field_serializer(
        "total_income",
        "total_expense",
        "total_positive",
        "total_negative",
        "net_cashflow",
        mode="plain",
    )
    def serialize_totals(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class CashflowSnapshotPagination(Pagination):
    """Pagination metadata for cashflow snapshot lists."""


class CashflowSnapshotListMeta(BaseModel):
    """Additional list metadata for cashflow snapshots."""

    tree_id: Optional[UUID] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class CashflowSnapshotListResponse(
    ListResponse[CashflowSnapshotSummaryResponse, CashflowSnapshotListMeta]
):
    """Schema for cashflow snapshot list response."""

    items: List[CashflowSnapshotSummaryResponse]
    pagination: CashflowSnapshotPagination
    meta: CashflowSnapshotListMeta


class CashflowSnapshotDetailResponse(BaseModel):
    id: UUID
    period_start: str
    period_end: str
    primary_currency: str
    tree_id: UUID
    snapshot_ts: Optional[str] = None
    total_income: Decimal
    total_expense: Decimal
    total_positive: Decimal
    total_negative: Decimal
    net_cashflow: Decimal
    summary: Optional[Dict[str, Any]] = None
    note: Optional[str]
    entries: List[CashflowSnapshotEntryResponse]
    exchange_rates: List[CashflowSnapshotExchangeRateResponse] = Field(
        default_factory=list
    )

    @field_serializer(
        "total_income",
        "total_expense",
        "total_positive",
        "total_negative",
        "net_cashflow",
        mode="plain",
    )
    def serialize_totals(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class CashflowSnapshotSourceChange(BaseModel):
    source_id: UUID
    source_name: str
    previous_amount: Decimal
    current_amount: Decimal
    delta: Decimal

    @field_serializer(
        "previous_amount",
        "current_amount",
        "delta",
        mode="plain",
    )
    def serialize_amount(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class CashflowSnapshotComparisonResponse(BaseModel):
    base_snapshot_id: UUID
    compare_snapshot_id: UUID
    base_period_start: str
    base_period_end: str
    compare_period_start: str
    compare_period_end: str
    base_totals: CashflowSnapshotSummaryResponse
    compare_totals: CashflowSnapshotSummaryResponse
    source_changes: List[CashflowSnapshotSourceChange]


class BillingApplyRequest(BaseModel):
    month: date
    source_ids: Optional[List[UUID]] = None
    tree_id: Optional[UUID] = None

    @field_validator("month", mode="before")
    @classmethod
    def parse_month(cls, value: Any) -> date:
        if isinstance(value, date):
            return value.replace(day=1)
        if isinstance(value, str):
            text = value.strip()
            if len(text) == 7:
                text = f"{text}-01"
            parsed = datetime.fromisoformat(f"{text}T00:00:00")
            return parsed.date().replace(day=1)
        raise ValueError("month must use format YYYY-MM")


class BillingCycleEntryPayload(BaseModel):
    cycle_start: date
    cycle_end: date
    amount: Decimal
    note: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def quantize_amount(cls, value: Decimal) -> Decimal:
        return value.quantize(EIGHT_PLACES)


class BillingCycleUpsertRequest(BaseModel):
    month: date
    entries: List[BillingCycleEntryPayload]

    @field_validator("month", mode="before")
    @classmethod
    def parse_month(cls, value: Any) -> date:
        return BillingApplyRequest.parse_month(value)


class BillingCycleEntryResponse(BaseModel):
    cycle_start: date
    cycle_end: date
    posted_month: date
    amount: Optional[Decimal]
    note: Optional[str]
    auto_generated: bool

    @field_serializer("amount", mode="plain")
    def serialize_amount(self, value: Optional[Decimal]) -> Optional[str]:
        return decimal_to_str(value) if value is not None else None


class BillingCycleHistoryResponse(BaseModel):
    source_id: UUID
    month: date
    cycles: List[BillingCycleEntryResponse]


class BillingCycleHistoryBulkResponse(BaseModel):
    source_id: UUID
    months: Dict[str, List[BillingCycleEntryResponse]]


class BillingMonthPagination(Pagination):
    """Pagination metadata for billing month lists."""


class BillingMonthListMeta(BaseModel):
    """Additional list metadata for billing months."""

    source_id: Optional[UUID] = None


class BillingMonthListResponse(ListResponse[str, BillingMonthListMeta]):
    """Schema for billing month list response."""

    items: List[str]
    pagination: BillingMonthPagination
    meta: BillingMonthListMeta


__all__ = [
    "CashflowSourceCreate",
    "CashflowSourceUpdate",
    "CashflowSourceNode",
    "CashflowSourceTreeResponse",
    "CashflowSourceTreeCreate",
    "CashflowSourceTreeUpdate",
    "CashflowSourceTreeItem",
    "CashflowSnapshotEntryInput",
    "CashflowSnapshotExchangeRateInput",
    "CashflowSnapshotExchangeRateResponse",
    "CashflowSnapshotCreateRequest",
    "CashflowSnapshotEntryResponse",
    "CashflowSnapshotSummaryResponse",
    "CashflowSnapshotListResponse",
    "CashflowSnapshotDetailResponse",
    "CashflowSnapshotSourceChange",
    "CashflowSnapshotComparisonResponse",
    "CashflowSnapshotUpdateRequest",
    "BillingApplyRequest",
    "BillingCycleEntryPayload",
    "BillingCycleUpsertRequest",
    "BillingCycleEntryResponse",
    "BillingCycleHistoryResponse",
    "BillingCycleHistoryBulkResponse",
    "BillingMonthListResponse",
]
