"""Stable identifiers shared by Hub Assistant entry points."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

HUB_ASSISTANT_PUBLIC_ID = "hub-assistant"
HUB_ASSISTANT_INTERNAL_ID: UUID = uuid5(
    NAMESPACE_URL,
    "hub-assistant://hub-assistant",
)
