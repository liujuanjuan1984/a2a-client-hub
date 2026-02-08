"""Helper utilities for building agent audit payloads."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence
from uuid import UUID

from app.agents.tools.responses import serialize_entity

MAX_TARGET_ENTITY_IDS = 25
MAX_TEXT_FIELD_LENGTH = 512
MAX_LIST_ITEMS = 12

# Minimal field whitelist to keep audit payloads focused
AUDIT_FIELD_WHITELIST: Dict[str, Sequence[str]] = {
    "actual_event": (
        "id",
        "title",
        "start_time",
        "end_time",
        "dimension_id",
        "task_id",
        "tracking_method",
        "location",
        "energy_level",
    ),
    "task": ("id", "title", "status", "due_date", "dimension_id", "priority"),
    "habit": ("id", "name", "status", "cadence", "dimension_id"),
    "habit_action": (
        "id",
        "habit_id",
        "status",
        "notes",
        "action_date",
    ),
    "person": ("id", "name", "relationship", "tags"),
    "note": ("id", "title", "summary", "dimension_id"),
    "vision": ("id", "title", "status", "target_date"),
    "tag": ("id", "name", "color"),
    "user_preference": ("id", "key", "value"),
    "invitation": ("id", "email", "status"),
}


def _stringify_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _truncate_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) <= MAX_TEXT_FIELD_LENGTH:
            return value
        return value[:MAX_TEXT_FIELD_LENGTH] + "..."
    if isinstance(value, list):
        truncated = [_truncate_value(item) for item in value[:MAX_LIST_ITEMS]]
        if len(value) > MAX_LIST_ITEMS:
            truncated.append("...")  # indicate omitted entries
        return truncated
    if isinstance(value, dict):
        return {k: _truncate_value(v) for k, v in value.items()}
    return value


def _apply_field_whitelist(
    snapshot: Dict[str, Any],
    entity_type: str,
) -> Dict[str, Any]:
    allowed_fields = AUDIT_FIELD_WHITELIST.get(entity_type)
    if not allowed_fields:
        return {key: _truncate_value(value) for key, value in snapshot.items()}
    allowed = set(allowed_fields)
    filtered = {
        key: _truncate_value(value)
        for key, value in snapshot.items()
        if key in allowed and value is not None
    }
    return filtered


def _wrap_snapshot(
    entity_id: Any, payload: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    if entity_id is None:
        return payload
    entity_key = _stringify_id(entity_id) or "unknown"
    return {entity_key: payload}


def ensure_snapshot(
    entity_or_snapshot: Any, entity_type: str
) -> Optional[Dict[str, Any]]:
    """
    Convert ORM entities or schemas into plain dictionaries suitable for audit storage.
    """

    if entity_or_snapshot is None:
        return None
    if isinstance(entity_or_snapshot, dict):
        snapshot = entity_or_snapshot
    else:
        snapshot = serialize_entity(entity_or_snapshot, entity_type)
    if not snapshot:
        return None
    filtered = _apply_field_whitelist(dict(snapshot), entity_type)
    if not filtered:
        return None
    return filtered


def build_target_entities(
    entity_type: str, ids: Iterable[Any]
) -> Optional[Dict[str, Any]]:
    cleaned: list[str] = []
    total = 0
    for identifier in ids:
        if identifier is None:
            continue
        total += 1
        if len(cleaned) < MAX_TARGET_ENTITY_IDS:
            cleaned.append(_stringify_id(identifier) or "")
    cleaned = [value for value in cleaned if value]
    if not cleaned:
        return None
    payload: Dict[str, Any] = {
        "type": entity_type,
        "ids": cleaned,
        "total_count": total,
    }
    if total > len(cleaned):
        payload["truncated"] = True
    return payload


def audit_for_entity(
    operation: str,
    *,
    entity_type: str,
    entity_id: Any | None = None,
    target_ids: Optional[Iterable[Any]] = None,
    before_snapshot: Any | None = None,
    after_snapshot: Any | None = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Assemble an audit payload for a single-entity operation.
    """

    targets = None
    if target_ids:
        targets = build_target_entities(entity_type, target_ids)
    elif entity_id is not None:
        targets = build_target_entities(entity_type, [entity_id])

    before_payload = (
        ensure_snapshot(before_snapshot, entity_type) if before_snapshot else None
    )
    after_payload = (
        ensure_snapshot(after_snapshot, entity_type) if after_snapshot else None
    )

    payload: Dict[str, Any] = {"operation": operation}
    if targets:
        payload["target_entities"] = targets
    if before_payload:
        payload["before_snapshot"] = _wrap_snapshot(entity_id, before_payload)
    if after_payload:
        payload["after_snapshot"] = _wrap_snapshot(entity_id, after_payload)
    if extra:
        payload["extra"] = extra

    return payload


__all__ = ["audit_for_entity", "ensure_snapshot", "build_target_entities"]
