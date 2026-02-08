"""Shared helpers for finance schemas."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

EIGHT_PLACES = Decimal("0.00000001")


def decimal_to_str(value: Optional[Decimal]) -> Optional[str]:
    """Render Decimal values without scientific notation."""
    if value is None:
        return None
    normalized = value.quantize(EIGHT_PLACES).normalize()
    if normalized == Decimal("-0"):
        normalized = Decimal("0")
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


__all__ = ["EIGHT_PLACES", "decimal_to_str"]
