"""Shared type definitions for the A2A client integration package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResolvedAgent:
    """Concrete agent information used for invocation."""

    name: str
    url: str
    description: str | None
    metadata: dict[str, Any]
    headers: dict[str, str]


__all__ = ["ResolvedAgent"]
