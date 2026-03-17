"""Shared normalized models for A2A peer selection and adapter requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class A2AInterfaceDescriptor:
    """Normalized transport declaration exposed by an agent card."""

    transport: str
    url: str
    protocol_version: str | None = None
    source: str = "card"


@dataclass(frozen=True, slots=True)
class A2APeerDescriptor:
    """Normalized peer metadata consumed by adapter selection."""

    agent_url: str
    selected_transport: str
    selected_url: str
    interfaces: tuple[A2AInterfaceDescriptor, ...]
    card: Any
    card_fingerprint: str
    supports_streaming: bool


@dataclass(frozen=True, slots=True)
class A2AMessageRequest:
    """Normalized invoke request passed to adapters."""

    query: str
    context_id: str | None = None
    metadata: dict[str, Any] | None = None
