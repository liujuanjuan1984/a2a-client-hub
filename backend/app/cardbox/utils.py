"""Helpers for mapping Compass domain objects to Cardbox identifiers."""

from __future__ import annotations

from datetime import date
from typing import Union
from uuid import UUID

from sqlalchemy import Column

from app.db.models.agent_session import AgentSession

_UUIDLike = Union[UUID, str, int, Column]


def _uuid_to_str(value: _UUIDLike) -> str:
    """Coerce different UUID representations to a canonical string."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Column):
        # For SQLAlchemy Column, we need to handle this differently
        # In practice, this should be resolved at the query level
        # For now, we'll raise an error to catch this at runtime
        raise ValueError(
            "Cannot convert SQLAlchemy Column to string directly. Use the actual UUID value instead."
        )
    return str(value)


def tenant_for_user(user_id: _UUIDLike) -> str:
    """Derive the Cardbox tenant identifier for a user."""

    return f"user-{_uuid_to_str(user_id)}"


def cardbox_for_session(session: Union[AgentSession, _UUIDLike]) -> str:
    """Return the Cardbox name for a conversation session."""

    session_id = session.id if isinstance(session, AgentSession) else session
    return f"session-{_uuid_to_str(session_id)}"


def daily_review_input_box(user_id: _UUIDLike, target_date: date) -> str:
    """Return the canonical daily review input Cardbox name.

    Naming follows ``review-input-{user_id}-{YYYY-MM-DD}`` as documented in
    docs/agentic/cardbox_integration.md. The box stores aggregated source data
    for the selected calendar day.
    """

    return f"review-input-{_uuid_to_str(user_id)}-{target_date.isoformat()}"


def daily_review_output_box(user_id: _UUIDLike, target_date: date) -> str:
    """Return the canonical daily review output Cardbox name.

    Naming follows ``review-output-{user_id}-{YYYY-MM-DD}`` per
    docs/agentic/cardbox_integration.md. The box stores the generated summary
    and action plan for the day.
    """

    return f"review-output-{_uuid_to_str(user_id)}-{target_date.isoformat()}"


def data_cardbox_name(user_id: _UUIDLike, module_key: str, target_date: date) -> str:
    """General helper for per-day data snapshots (timelog, notes, etc.)."""

    safe_module = module_key.replace(" ", "-").lower()
    return f"data-{safe_module}-{_uuid_to_str(user_id)}-{target_date.isoformat()}"


__all__ = [
    "tenant_for_user",
    "cardbox_for_session",
    "daily_review_input_box",
    "daily_review_output_box",
    "data_cardbox_name",
]
