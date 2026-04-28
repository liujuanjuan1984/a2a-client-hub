from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from a2a.types import AgentCard

from app.integrations.a2a_client.protobuf import parse_agent_card as _parse_agent_card


def parse_agent_card(payload: Mapping[str, Any]) -> AgentCard:
    """Parse test AgentCard payloads via the protobuf-native helper."""

    return _parse_agent_card(payload)
