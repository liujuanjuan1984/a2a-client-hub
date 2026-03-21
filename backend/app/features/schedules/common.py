"""Common types and errors for A2A schedule services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from app.db.locking import (
    to_retryable_db_lock_error,
    to_retryable_db_query_timeout_error,
)


class A2AScheduleError(RuntimeError):
    """Base error for A2A schedule operations."""


class A2AScheduleNotFoundError(A2AScheduleError):
    """Raised when a schedule cannot be located for the user."""


class A2AScheduleValidationError(A2AScheduleError):
    """Raised when schedule payload validation fails."""


class A2AScheduleQuotaError(A2AScheduleError):
    """Raised when a schedule task operation exceeds user quotas."""


class A2AScheduleConflictError(A2AScheduleError):
    """Raised when a schedule task operation is in conflict with its current state."""


class A2AScheduleServiceBusyError(A2AScheduleError):
    """Raised when a schedule operation times out due to transient DB pressure."""


@dataclass(frozen=True)
class ClaimedA2AScheduleTask:
    """Snapshot describing a due task claimed by the scheduler."""

    task_id: UUID
    user_id: UUID
    agent_id: UUID
    conversation_id: UUID | None
    name: str
    prompt: str
    cycle_type: str
    time_point: dict[str, Any]
    scheduled_for: datetime
    run_id: UUID


_ScheduleResultT = TypeVar("_ScheduleResultT")


def map_retryable_db_errors(
    operation: str,
) -> Callable[
    [Callable[..., Awaitable[_ScheduleResultT]]],
    Callable[..., Awaitable[_ScheduleResultT]],
]:
    def decorator(
        fn: Callable[..., Awaitable[_ScheduleResultT]],
    ) -> Callable[..., Awaitable[_ScheduleResultT]]:
        @wraps(fn)
        async def wrapper(
            self: Any,
            *args: Any,
            **kwargs: Any,
        ) -> _ScheduleResultT:
            try:
                return await fn(self, *args, **kwargs)
            except DBAPIError as exc:
                retryable_lock_error = to_retryable_db_lock_error(
                    exc,
                    lock_message=(
                        f"{operation} is currently locked by another operation; retry shortly."
                    ),
                )
                if retryable_lock_error is not None:
                    raise A2AScheduleConflictError(str(retryable_lock_error)) from exc

                retryable_timeout_error = to_retryable_db_query_timeout_error(
                    exc,
                    timeout_message=f"{operation} timed out; service busy, retry shortly.",
                )
                if retryable_timeout_error is not None:
                    raise A2AScheduleServiceBusyError(
                        str(retryable_timeout_error)
                    ) from exc
                raise

        return wrapper

    return decorator


A2A_SCHEDULE_SOURCE = "scheduled"
A2A_MANUAL_SOURCE = "manual"
