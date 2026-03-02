"""Database locking helpers for PostgreSQL-specific concurrency control."""

from __future__ import annotations

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


def _extract_sqlstate(exc: Exception) -> str | None:
    if not isinstance(exc, DBAPIError):
        return None
    original = getattr(exc, "orig", None)
    if original is None:
        return None
    for key in ("sqlstate", "pgcode"):
        value = getattr(original, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
        return "statement timeout" in message

    return "statement timeout" in message


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
    "is_postgres_lock_not_available_error",
    "is_postgres_statement_timeout_error",
    "set_postgres_local_timeouts",
]
