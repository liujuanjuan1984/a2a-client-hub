"""Stable identifiers shared by self-management entry points."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID = "self-management-assistant"
SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID: UUID = uuid5(
    NAMESPACE_URL,
    "builtin://self-management-assistant",
)

__all__ = [
    "SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID",
    "SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID",
]
