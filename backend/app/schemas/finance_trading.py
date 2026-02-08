"""Schemas for trading plan management."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.finance_common import decimal_to_str
from app.schemas.pagination import ListResponse, Pagination

ROI_PLACES = Decimal("0.0001")
AMOUNT_PLACES = Decimal("0.00000001")


def _normalize_decimal(value: Optional[Decimal], places: Decimal) -> Optional[Decimal]:
    if value is None:
        return None
    return value.quantize(places)


class TradingPlanBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_roi: Optional[Decimal] = Field(None, ge=-1000, le=1000)
    note: Optional[str] = Field(None, max_length=4000)
    status: Literal["draft", "active", "archived"] = "draft"

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        return text or None

    @field_validator("target_roi")
    @classmethod
    def normalize_roi(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        return _normalize_decimal(value, ROI_PLACES)

    @model_validator(mode="after")
    def validate_period(self) -> "TradingPlanBase":
        if (
            self.period_start
            and self.period_end
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end cannot be earlier than period_start")
        return self


class TradingPlanCreate(TradingPlanBase):
    pass


class TradingPlanUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    target_roi: Optional[Decimal] = Field(None, ge=-1000, le=1000)
    note: Optional[str] = Field(None, max_length=4000)
    status: Optional[Literal["draft", "active", "archived"]] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        if not text:
            raise ValueError("name must not be empty")
        return text

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        text = value.strip()
        return text or None

    @field_validator("target_roi")
    @classmethod
    def normalize_roi(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        return _normalize_decimal(value, ROI_PLACES)

    @model_validator(mode="after")
    def validate_period(self) -> "TradingPlanUpdate":
        if (
            self.period_start
            and self.period_end
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end cannot be earlier than period_start")
        return self


class TradingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    target_roi: Optional[Decimal]
    note: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("target_roi")
    def serialize_target_roi(self, value: Optional[Decimal], _info) -> Optional[str]:
        return decimal_to_str(value)


class TradingPlanPagination(Pagination):
    """Pagination metadata for trading plans."""


class TradingPlanListMeta(BaseModel):
    """Additional list metadata for trading plans."""

    include_archived: Optional[bool] = None


class TradingPlanListResponse(ListResponse[TradingPlanResponse, TradingPlanListMeta]):
    items: List[TradingPlanResponse]
    pagination: TradingPlanPagination
    meta: TradingPlanListMeta


def _normalize_symbol(symbol: str) -> str:
    text = symbol.strip().upper()
    for sep in ("/", "-", "_"):
        if sep in text:
            parts = [segment for segment in text.split(sep) if segment]
            if len(parts) == 2:
                return f"{parts[0]}/{parts[1]}"
    if len(text) >= 2:
        midpoint = len(text) // 2
        return f"{text[:midpoint]}/{text[midpoint:]}"
    raise ValueError("symbol must include base and quote assets")


class TradingInstrumentBase(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=64)
    base_asset: Optional[str] = Field(None, min_length=2, max_length=32)
    quote_asset: Optional[str] = Field(None, min_length=2, max_length=32)
    exchange: Optional[str] = Field(None, max_length=64)
    strategy_tag: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def ensure_assets(self) -> "TradingInstrumentBase":
        normalized_symbol = _normalize_symbol(self.symbol)
        base, quote = normalized_symbol.split("/")
        provided_base = (self.base_asset or "").strip().upper()
        provided_quote = (self.quote_asset or "").strip().upper()
        base_asset = provided_base or base
        quote_asset = provided_quote or quote
        if not base_asset or not quote_asset:
            raise ValueError("base_asset and quote_asset cannot be empty")
        self.symbol = f"{base_asset}/{quote_asset}"
        self.base_asset = base_asset
        self.quote_asset = quote_asset
        if self.exchange:
            self.exchange = self.exchange.strip() or None
        if self.strategy_tag:
            self.strategy_tag = self.strategy_tag.strip() or None
        if self.note:
            self.note = self.note.strip() or None
        return self


class TradingInstrumentCreate(TradingInstrumentBase):
    pass


class TradingInstrumentUpdate(BaseModel):
    symbol: Optional[str] = Field(None, min_length=3, max_length=64)
    base_asset: Optional[str] = Field(None, min_length=2, max_length=32)
    quote_asset: Optional[str] = Field(None, min_length=2, max_length=32)
    exchange: Optional[str] = Field(None, max_length=64)
    strategy_tag: Optional[str] = Field(None, max_length=64)
    note: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def ensure_assets(self) -> "TradingInstrumentUpdate":
        if not any((self.symbol, self.base_asset, self.quote_asset)):
            return self
        symbol = _normalize_symbol(self.symbol) if self.symbol else None
        base_from_symbol, quote_from_symbol = (None, None)
        if symbol:
            base_from_symbol, quote_from_symbol = symbol.split("/")
        if self.base_asset:
            base = self.base_asset.strip().upper()
        else:
            base = base_from_symbol
        if self.quote_asset:
            quote = self.quote_asset.strip().upper()
        else:
            quote = quote_from_symbol
        if not base or not quote:
            raise ValueError("symbol or explicit base/quote must be provided together")
        self.symbol = f"{base}/{quote}"
        self.base_asset = base
        self.quote_asset = quote
        if self.exchange is not None:
            self.exchange = self.exchange.strip() or None
        if self.strategy_tag is not None:
            self.strategy_tag = self.strategy_tag.strip() or None
        if self.note is not None:
            self.note = self.note.strip() or None
        return self


class TradingInstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    symbol: str
    base_asset: str
    quote_asset: str
    exchange: Optional[str]
    strategy_tag: Optional[str]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class TradingInstrumentPagination(Pagination):
    """Pagination metadata for trading instruments."""


class TradingInstrumentListMeta(BaseModel):
    """Additional list metadata for trading instruments."""

    plan_id: Optional[UUID] = None


class TradingInstrumentListResponse(
    ListResponse[TradingInstrumentResponse, TradingInstrumentListMeta]
):
    items: List[TradingInstrumentResponse]
    pagination: TradingInstrumentPagination
    meta: TradingInstrumentListMeta


class TradingEntryBase(BaseModel):
    plan_id: UUID
    instrument_id: UUID
    trade_time: datetime
    direction: Literal["buy", "sell", "transfer"]
    base_delta: Decimal
    quote_delta: Decimal
    price: Optional[Decimal] = None
    fee_asset: Optional[str] = Field(None, max_length=32)
    fee_amount: Optional[Decimal] = None
    source: Literal["manual", "import"] = "manual"
    note: Optional[str] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def normalize_fields(self) -> "TradingEntryBase":
        self.base_delta = _normalize_decimal(self.base_delta, AMOUNT_PLACES) or Decimal(
            "0"
        )
        self.quote_delta = _normalize_decimal(
            self.quote_delta, AMOUNT_PLACES
        ) or Decimal("0")
        if self.price is not None:
            self.price = _normalize_decimal(self.price, AMOUNT_PLACES)
        if self.fee_amount is not None:
            self.fee_amount = _normalize_decimal(self.fee_amount, AMOUNT_PLACES)
        if self.fee_asset:
            self.fee_asset = self.fee_asset.strip().upper()
        if self.note:
            text = self.note.strip()
            self.note = text or None
        return self


class TradingEntryCreate(TradingEntryBase):
    pass


class TradingEntryUpdate(BaseModel):
    trade_time: Optional[datetime] = None
    direction: Optional[Literal["buy", "sell", "transfer"]] = None
    base_delta: Optional[Decimal] = None
    quote_delta: Optional[Decimal] = None
    price: Optional[Decimal] = None
    fee_asset: Optional[str] = Field(None, max_length=32)
    fee_amount: Optional[Decimal] = None
    source: Optional[Literal["manual", "import"]] = None
    note: Optional[str] = Field(None, max_length=4000)

    @model_validator(mode="after")
    def normalize_fields(self) -> "TradingEntryUpdate":
        if self.base_delta is not None:
            self.base_delta = _normalize_decimal(self.base_delta, AMOUNT_PLACES)
        if self.quote_delta is not None:
            self.quote_delta = _normalize_decimal(self.quote_delta, AMOUNT_PLACES)
        if self.price is not None:
            self.price = _normalize_decimal(self.price, AMOUNT_PLACES)
        if self.fee_amount is not None:
            self.fee_amount = _normalize_decimal(self.fee_amount, AMOUNT_PLACES)
        if self.fee_asset is not None:
            self.fee_asset = self.fee_asset.strip().upper() or None
        if self.note is not None:
            note = self.note.strip()
            self.note = note or None
        return self


class TradingEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: UUID
    instrument_id: UUID
    trade_time: datetime
    direction: str
    base_delta: Decimal
    quote_delta: Decimal
    price: Optional[Decimal]
    fee_asset: Optional[str]
    fee_amount: Optional[Decimal]
    source: str
    note: Optional[str]
    created_at: datetime
    updated_at: datetime

    @field_serializer("base_delta", "quote_delta", "price", "fee_amount")
    def serialize_decimal(self, value: Optional[Decimal], _info):
        return decimal_to_str(value)


class TradingEntryPagination(Pagination):
    """Pagination metadata for trading entries."""


class TradingEntryListMeta(BaseModel):
    """Additional list metadata for trading entries."""

    plan_id: Optional[UUID] = None
    instrument_id: Optional[UUID] = None
    direction: Optional[Literal["buy", "sell", "transfer"]] = None
    source: Optional[Literal["manual", "import"]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class TradingEntryListResponse(
    ListResponse[TradingEntryResponse, TradingEntryListMeta]
):
    items: List[TradingEntryResponse]
    pagination: TradingEntryPagination
    meta: TradingEntryListMeta


class TradingInstrumentSummary(BaseModel):
    instrument_id: UUID
    plan_id: UUID
    symbol: str
    base_asset: str
    quote_asset: str
    net_position: Decimal
    net_position_quote: Decimal
    avg_entry_price: Optional[Decimal]
    market_price: Optional[Decimal]
    market_value_primary: Decimal
    market_value_primary_base: Decimal
    market_value_primary_quote: Decimal
    realized_pnl_primary: Decimal
    unrealized_pnl_primary: Decimal
    invested_primary: Decimal
    roi: Optional[Decimal]
    updated_at: datetime

    @field_serializer(
        "net_position",
        "net_position_quote",
        "avg_entry_price",
        "market_price",
        "market_value_primary",
        "market_value_primary_base",
        "market_value_primary_quote",
        "realized_pnl_primary",
        "unrealized_pnl_primary",
        "invested_primary",
        "roi",
    )
    def serialize_decimal(self, value: Optional[Decimal], _info):
        return decimal_to_str(value) if value is not None else None


class TradingPlanSummaryTotals(BaseModel):
    total_investment: Decimal
    total_realized: Decimal
    total_unrealized: Decimal
    net_value: Decimal
    roi: Optional[Decimal]

    @field_serializer(
        "total_investment",
        "total_realized",
        "total_unrealized",
        "net_value",
        "roi",
    )
    def serialize_decimal(self, value: Optional[Decimal], _info):
        return decimal_to_str(value) if value is not None else None


class TradingPlanExchangeRateUsage(BaseModel):
    base_asset: str
    quote_asset: str
    rate: Decimal
    scope: Literal["plan", "user", "global", "synthetic"]
    derived: bool = False
    source: Optional[str] = None
    captured_at: Optional[datetime] = None

    @field_serializer("rate", mode="plain")
    def serialize_rate(self, value: Decimal) -> str:
        return decimal_to_str(value) or "0"


class TradingPlanSummaryResponse(BaseModel):
    plan_id: UUID
    plan_name: str
    plan_status: str
    primary_currency: str
    calculated_at: datetime
    totals: TradingPlanSummaryTotals
    instruments: List[TradingInstrumentSummary]
    rates_used: List[TradingPlanExchangeRateUsage] = Field(default_factory=list)
    rates_updated_at: Optional[datetime] = None
    rate_mode: Literal["snapshot", "source"] = "snapshot"
    rate_snapshot_ts: Optional[datetime] = None


__all__ = [
    "TradingPlanCreate",
    "TradingPlanUpdate",
    "TradingPlanResponse",
    "TradingPlanListResponse",
    "TradingPlanPagination",
    "TradingPlanListMeta",
    "TradingInstrumentCreate",
    "TradingInstrumentUpdate",
    "TradingInstrumentResponse",
    "TradingInstrumentListResponse",
    "TradingInstrumentPagination",
    "TradingInstrumentListMeta",
    "TradingEntryCreate",
    "TradingEntryUpdate",
    "TradingEntryResponse",
    "TradingEntryListResponse",
    "TradingEntryPagination",
    "TradingEntryListMeta",
    "TradingInstrumentSummary",
    "TradingPlanSummaryTotals",
    "TradingPlanExchangeRateUsage",
    "TradingPlanSummaryResponse",
]
