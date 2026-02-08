"""Schemas for exchange rate APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.schemas.finance_common import decimal_to_str
from app.schemas.pagination import ListResponse, Pagination


class ExchangeRateCreateRequest(BaseModel):
    base_asset: str = Field(..., min_length=2, max_length=32)
    quote_asset: str = Field(..., min_length=2, max_length=32)
    rate: Decimal = Field(..., gt=Decimal("0"))
    source: Optional[str] = Field("manual", max_length=64)
    captured_at: datetime
    plan_id: Optional[UUID] = None

    @field_validator("base_asset", "quote_asset")
    @classmethod
    def upper_assets(cls, value: str) -> str:
        text = value.strip().upper()
        if not text:
            raise ValueError("asset symbol cannot be empty")
        return text

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = value.strip()
        return text or None


class ExchangeRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan_id: Optional[UUID]
    base_asset: str
    quote_asset: str
    rate: Decimal
    source: str
    captured_at: datetime
    created_at: datetime

    @field_serializer("rate")
    def render_rate(self, value: Decimal, _info) -> str:
        return decimal_to_str(value)


class ExchangeRatePagination(Pagination):
    """Pagination metadata for exchange rate lists."""


class ExchangeRateListMeta(BaseModel):
    """Additional list metadata for exchange rate listings."""

    plan_id: Optional[UUID] = None


class ExchangeRateListResponse(
    ListResponse[ExchangeRateResponse, ExchangeRateListMeta]
):
    """Schema for exchange rate list response."""

    items: List[ExchangeRateResponse]
    pagination: ExchangeRatePagination
    meta: ExchangeRateListMeta


class ExchangeRateQueryResult(BaseModel):
    base_asset: str
    quote_asset: str
    rate: Decimal
    source: Optional[str] = None
    captured_at: Optional[datetime] = None

    @field_serializer("rate")
    def render_rate(self, value: Decimal, _info) -> Optional[str]:
        if value is None:
            return None
        return decimal_to_str(value)


class ExchangeRateQueryResponse(BaseModel):
    requested_at: datetime
    pairs: List[ExchangeRateQueryResult]


__all__ = [
    "ExchangeRateCreateRequest",
    "ExchangeRateListResponse",
    "ExchangeRateResponse",
    "ExchangeRateQueryResponse",
    "ExchangeRateQueryResult",
]
