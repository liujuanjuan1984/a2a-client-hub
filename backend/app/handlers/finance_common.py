"""Shared primitives and errors for finance handlers."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

EIGHT_PLACES = Decimal("0.00000001")
SIX_PLACES = Decimal("0.000001")


class FinanceError(Exception):
    """Base class for finance-related errors."""


class FinanceAccountNotFoundError(FinanceError):
    """Raised when a finance account cannot be located."""


class FinanceAccountNameConflictError(FinanceError):
    """Raised when a sibling account shares the same name."""


class FinanceParentNotAllowedError(FinanceError):
    """Raised when an invalid parent relationship is requested."""


class MissingExchangeRateError(FinanceError):
    """Raised when a required exchange rate is missing for snapshot creation."""


class RateSnapshotNotReadyError(FinanceError):
    """Raised when a rate snapshot has not been created yet."""


class DuplicateExchangeRateError(FinanceError):
    """Raised when duplicate exchange rates are provided for the same currency."""


class EmptySnapshotPayloadError(FinanceError):
    """Raised when a snapshot is attempted without any values."""


class CashflowSourceNotFoundError(FinanceError):
    """Raised when a cashflow source is missing."""


class CashflowSourceNameConflictError(FinanceError):
    """Raised when duplicate cashflow source names exist under the same parent."""


class FinanceTreeNotFoundError(FinanceError):
    """Raised when a finance tree cannot be located."""


class FinanceTreeNameConflictError(FinanceError):
    """Raised when a tree name already exists for the user."""


class FinanceTreeNotEmptyError(FinanceError):
    """Raised when attempting to delete a tree that still has data."""


class FinanceTreeDeleteForbiddenError(FinanceError):
    """Raised when a tree cannot be deleted due to policy constraints."""


def slugify(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "account"


def build_path(parent_path: Optional[str], slug: str) -> str:
    if parent_path:
        return f"{parent_path.rstrip('/')}/{slug}"
    return f"/{slug}"


def compute_depth(path: str) -> int:
    segments = [segment for segment in path.split("/") if segment]
    return max(len(segments) - 1, 0)


def to_json_number(value: Decimal) -> float:
    return float(value.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP))


def from_json_number(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError(f"Unsupported numeric value: {value!r}")


__all__ = [
    "EIGHT_PLACES",
    "SIX_PLACES",
    "FinanceError",
    "FinanceAccountNotFoundError",
    "FinanceAccountNameConflictError",
    "FinanceParentNotAllowedError",
    "MissingExchangeRateError",
    "RateSnapshotNotReadyError",
    "DuplicateExchangeRateError",
    "EmptySnapshotPayloadError",
    "CashflowSourceNotFoundError",
    "CashflowSourceNameConflictError",
    "FinanceTreeNotFoundError",
    "FinanceTreeNameConflictError",
    "FinanceTreeNotEmptyError",
    "FinanceTreeDeleteForbiddenError",
    "slugify",
    "build_path",
    "compute_depth",
    "to_json_number",
    "from_json_number",
]
