"""Database locking helpers for PostgreSQL-specific concurrency control."""

from __future__ import annotations

from enum import Enum

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

_PG_SQLSTATE_LOCK_NOT_AVAILABLE = "55P03"
_PG_SQLSTATE_QUERY_CANCELED = "57014"
_LOCK_NOT_AVAILABLE_MARKERS = (
    "could not obtain lock on row",
    "lock not available",
    "canceling statement due to lock timeout",
)
_STATEMENT_TIMEOUT_MARKERS = (
    "canceling statement due to statement timeout",
    "statement timeout",
    "query timeout",
    "query timed out",
)
_NON_STATEMENT_TIMEOUT_MARKERS = (
    "timeout while waiting for connection",
    "waiting for connection",
    "connection timeout",
    "pool timeout",
)


class DbLockFailureKind(str, Enum):
    LOCK_NOT_AVAILABLE = "lock_not_available"


class RetryableDbLockError(RuntimeError):
    """Domain error for DB lock contention that can be retried."""

    def __init__(self, message: str, *, kind: DbLockFailureKind) -> None:
        super().__init__(message)
        self.kind = kind


class RetryableDbQueryTimeoutError(RuntimeError):
    """Domain error for query timeout that can be retried later."""


def _extract_sqlstate_value(error_obj: object | None) -> str | None:
    if error_obj is None:
        return None

    for key in ("sqlstate", "pgcode"):
        value = getattr(error_obj, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    diag = getattr(error_obj, "diag", None)
    for key in ("sqlstate", "pgcode"):
        value = getattr(diag, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def _extract_sqlstate(exc: Exception) -> str | None:
    if not isinstance(exc, DBAPIError):
        return None
    original = getattr(exc, "orig", None)
    if original is None:
        return None

    for candidate in (
        original,
        getattr(original, "__cause__", None),
        getattr(original, "__context__", None),
    ):
        value = _extract_sqlstate_value(candidate)
        if value is not None:
            return value

    return None


def _looks_like_statement_timeout(message: str) -> bool:
    if any(marker in message for marker in _NON_STATEMENT_TIMEOUT_MARKERS):
        return False
    return any(marker in message for marker in _STATEMENT_TIMEOUT_MARKERS)


def is_postgres_lock_not_available_error(exc: Exception) -> bool:
    sqlstate = _extract_sqlstate(exc)
    if sqlstate == _PG_SQLSTATE_LOCK_NOT_AVAILABLE:
        return True

    if not isinstance(exc, DBAPIError):
        return False
    message = str(getattr(exc, "orig", exc)).lower()
    return any(marker in message for marker in _LOCK_NOT_AVAILABLE_MARKERS)


def is_postgres_statement_timeout_error(exc: Exception) -> bool:
    if not isinstance(exc, DBAPIError):
        return False

    message = str(getattr(exc, "orig", exc)).lower()
    sqlstate = _extract_sqlstate(exc)
    if sqlstate == _PG_SQLSTATE_QUERY_CANCELED:
        return _looks_like_statement_timeout(message)

    if sqlstate:
        return False

    # Fallback for proxies/drivers that omit sqlstate but keep timeout keywords.
    return _looks_like_statement_timeout(message)


def classify_postgres_lock_failure(exc: Exception) -> DbLockFailureKind | None:
    if isinstance(exc, RetryableDbLockError):
        return exc.kind

    if is_postgres_lock_not_available_error(exc):
        return DbLockFailureKind.LOCK_NOT_AVAILABLE
    return None


def is_retryable_db_lock_failure(exc: Exception) -> bool:
    return classify_postgres_lock_failure(exc) is not None


def is_retryable_db_query_timeout(exc: Exception) -> bool:
    if isinstance(exc, RetryableDbQueryTimeoutError):
        return True
    return is_postgres_statement_timeout_error(exc)


def to_retryable_db_lock_error(
    exc: Exception,
    *,
    lock_message: str,
) -> RetryableDbLockError | None:
    if isinstance(exc, RetryableDbLockError):
        return exc

    kind = classify_postgres_lock_failure(exc)
    if kind is None:
        return None

    return RetryableDbLockError(lock_message, kind=kind)


def to_retryable_db_query_timeout_error(
    exc: Exception,
    *,
    timeout_message: str,
) -> RetryableDbQueryTimeoutError | None:
    if isinstance(exc, RetryableDbQueryTimeoutError):
        return exc
    if not is_postgres_statement_timeout_error(exc):
        return None
    return RetryableDbQueryTimeoutError(timeout_message)


async def set_postgres_local_timeouts(
    db: AsyncSession,
    *,
    lock_timeout_ms: int | None = None,
    statement_timeout_ms: int | None = None,
) -> None:
    """Apply transaction-local PostgreSQL timeout settings when supported."""

    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name != "postgresql":
        return

    if lock_timeout_ms is not None and int(lock_timeout_ms) > 0:
        lock_timeout_value = f"{int(lock_timeout_ms)}ms"
        await db.execute(
            text(f"SET LOCAL lock_timeout = '{lock_timeout_value}'"),
        )
    if statement_timeout_ms is not None and int(statement_timeout_ms) > 0:
        statement_timeout_value = f"{int(statement_timeout_ms)}ms"
        await db.execute(
            text(f"SET LOCAL statement_timeout = '{statement_timeout_value}'"),
        )


__all__ = [
    "DbLockFailureKind",
    "RetryableDbLockError",
    "RetryableDbQueryTimeoutError",
    "classify_postgres_lock_failure",
    "is_retryable_db_lock_failure",
    "is_retryable_db_query_timeout",
    "is_postgres_lock_not_available_error",
    "is_postgres_statement_timeout_error",
    "set_postgres_local_timeouts",
    "to_retryable_db_lock_error",
    "to_retryable_db_query_timeout_error",
]
