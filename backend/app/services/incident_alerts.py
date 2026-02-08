"""
Administrative incident notifications.

This module provides helper utilities to surface critical backend incidents,
such as LLM provider outages, to administrator users via the existing system
notification channel. A lightweight in-memory deduplication window is used to
avoid spamming duplicate alerts while an incident is ongoing.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.agent_message import AgentMessage
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.services.notifications import NotificationServiceError, send_notification

logger = get_logger(__name__)

_INCIDENT_CACHE: Dict[str, float] = {}
_CACHE_LOCK = threading.Lock()
_DEFAULT_DEDUPE_SECONDS = 600  # 10 minutes


def _now() -> float:
    return time.monotonic()


async def _list_admin_user_ids(db: AsyncSession) -> list[UUID]:
    """Return identifiers for active administrator accounts."""

    result = await db.execute(
        select(User.id)
        .where(User.is_superuser.is_(True))
        .where(User.disabled_at.is_(None))
    )
    return list(result.scalars().all())


def _release_reservation(incident_key: str, reservation_time: float) -> None:
    """Remove a pending incident reservation if it still matches the provided marker."""

    with _CACHE_LOCK:
        if _INCIDENT_CACHE.get(incident_key) == reservation_time:
            _INCIDENT_CACHE.pop(incident_key, None)


async def notify_admins_of_incident(
    incident_key: str,
    title: str,
    body: str,
    *,
    severity: str = AgentMessage.SEVERITY_WARNING,
    metadata: Dict[str, Any] | None = None,
    dedupe_seconds: int = _DEFAULT_DEDUPE_SECONDS,
) -> bool:
    """
    Send a one-off incident notification to administrators.

    A per-incident deduplication window prevents repeated alerts for the same
    issue from flooding the notification channel.
    """

    current_time = _now()
    with _CACHE_LOCK:
        last_sent = _INCIDENT_CACHE.get(incident_key)
        if last_sent is not None and (current_time - last_sent) < dedupe_seconds:
            logger.debug(
                "Skipping incident notification due to active dedupe window.",
                extra={"incident_key": incident_key},
            )
            return False
        # Temporarily reserve the slot; if sending fails we will clear it.
        _INCIDENT_CACHE[incident_key] = current_time

    admin_ids: list[UUID] = []
    try:
        async with AsyncSessionLocal() as db:
            admin_ids = await _list_admin_user_ids(db)
            if not admin_ids:
                logger.info(
                    "No admin users available; incident notification suppressed.",
                    extra={"incident_key": incident_key},
                )
                _release_reservation(incident_key, current_time)
                return False

            try:
                await send_notification(
                    db,
                    user_ids=admin_ids,
                    body=body,
                    title=title,
                    severity=severity,
                    metadata={
                        "incident_key": incident_key,
                        **(metadata or {}),
                    },
                    sync_cardbox=False,
                )
            except NotificationServiceError as exc:
                logger.error(
                    "Failed to dispatch admin incident notification: %s",
                    exc,
                    exc_info=exc,
                    extra={"incident_key": incident_key},
                )
                _release_reservation(incident_key, current_time)
                return False
    except Exception:
        _release_reservation(incident_key, current_time)
        raise

    with _CACHE_LOCK:
        _INCIDENT_CACHE[incident_key] = _now()

    logger.info(
        "Dispatched admin incident notification.",
        extra={
            "incident_key": incident_key,
            "admin_count": len(admin_ids),
        },
    )
    return True


try:  # pragma: no cover - litellm may not be installed in some environments.
    from litellm import exceptions as litellm_exceptions  # type: ignore
except Exception:  # pragma: no cover - defensive
    litellm_exceptions = None  # type: ignore[assignment]


async def report_llm_failure(
    operation_name: str,
    exc: Exception,
    *,
    context: Mapping[str, Any] | None = None,
    dedupe_seconds: int = _DEFAULT_DEDUPE_SECONDS,
) -> bool:
    """
    Notify administrators about an LLM-related failure.

    Returns:
        True if a notification was sent, False otherwise.
    """

    ctx = dict(context or {})
    model = ctx.get("model")
    tools_count = ctx.get("tools_count")
    duration = ctx.get("duration")

    error_type = type(exc).__name__
    incident_base = "llm-error"
    severity = AgentMessage.SEVERITY_WARNING
    guidance: str | None = None

    if litellm_exceptions is not None:
        auth_error = getattr(litellm_exceptions, "AuthenticationError", None)
        rate_limit_error = getattr(litellm_exceptions, "RateLimitError", None)
        service_unavailable = getattr(
            litellm_exceptions, "ServiceUnavailableError", None
        )

        if auth_error and isinstance(exc, auth_error):
            severity = AgentMessage.SEVERITY_CRITICAL
            incident_base = "llm-auth"
            guidance = "LLM authentication failed. Please verify API credentials."
        elif rate_limit_error and isinstance(exc, rate_limit_error):
            severity = AgentMessage.SEVERITY_WARNING
            incident_base = "llm-rate-limit"
            guidance = "LLM provider rate limit reached. Consider reducing load or upgrading plan."
        elif service_unavailable and isinstance(exc, service_unavailable):
            severity = AgentMessage.SEVERITY_CRITICAL
            incident_base = "llm-service-unavailable"
            guidance = (
                "LLM provider reported service unavailability. Monitor provider status."
            )

    model_key = str(model).lower() if model else "unknown"
    incident_key = f"{incident_base}:{model_key}"

    lines = [
        f"{operation_name} failed ({error_type}).",
    ]
    if model:
        lines.append(f"Model: {model}")
    if tools_count is not None:
        lines.append(f"Tools requested: {tools_count}")
    lines.append(f"Details: {exc}")
    if guidance:
        lines.append(guidance)
    if isinstance(duration, (int, float)):
        lines.append(f"Duration before failure: {duration:.3f}s")

    metadata: Dict[str, Any] = {
        "operation": operation_name,
        "error_type": error_type,
        "error_message": str(exc),
    }
    if model:
        metadata["model"] = model
    if tools_count is not None:
        metadata["tools_count"] = tools_count
    if isinstance(duration, (int, float)):
        metadata["duration"] = float(duration)

    return await notify_admins_of_incident(
        incident_key,
        title="LLM Service Error",
        body="\n".join(lines),
        severity=severity,
        metadata=metadata,
        dedupe_seconds=dedupe_seconds,
    )


__all__ = ["notify_admins_of_incident", "report_llm_failure"]
