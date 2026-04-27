"""Helpers for normalizing upstream A2A task payloads."""

from __future__ import annotations

from typing import Any

from app.integrations.a2a_client.protobuf import to_json_like


def normalize_task_payload(task: Any) -> dict[str, Any] | None:
    """Return a JSON-like dict for task payloads from SDK or JSON-RPC adapters."""

    normalized = to_json_like(task)
    return normalized if isinstance(normalized, dict) else None


def _to_json_like(value: Any) -> Any:
    return to_json_like(value)
