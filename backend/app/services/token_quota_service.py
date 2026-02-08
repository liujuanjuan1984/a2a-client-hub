"""Daily token quota management helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.user import User
from app.db.models.user_daily_llm_usage import UserDailyLlmUsage
from app.utils.timezone_util import utc_today


class DailyTokenQuotaExceededError(RuntimeError):
    """Raised when user's daily token consumption reaches the limit."""

    def __init__(self, *, limit: int, used: int, reset_at: datetime):
        self.limit = limit
        self.used = used
        self.reset_at = reset_at
        super().__init__(
            "Daily LLM token limit reached. Please wait for the next UTC natural day or contact administrator."
        )


TokenSource = Literal["system", "user"]


@dataclass(frozen=True)
class DailyUsageHandle:
    """Lightweight handle passed to business layer for post-hoc token accumulation."""

    user_id: UUID
    usage_date: date
    token_source: TokenSource


def _reset_at(usage_date: date) -> datetime:
    return datetime.combine(usage_date + timedelta(days=1), time(tzinfo=timezone.utc))


async def _query_usage(
    db: AsyncSession, user_id: UUID, usage_date: date
) -> Optional[UserDailyLlmUsage]:
    stmt = (
        select(UserDailyLlmUsage)
        .where(
            UserDailyLlmUsage.user_id == user_id,
            UserDailyLlmUsage.usage_date == usage_date,
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalars().first()


async def _get_or_create_usage(
    db: AsyncSession, user_id: UUID, usage_date: date
) -> UserDailyLlmUsage:
    usage = await _query_usage(db, user_id, usage_date)
    if usage is not None:
        return usage

    insert_stmt = (
        insert(UserDailyLlmUsage)
        .values(user_id=user_id, usage_date=usage_date)
        .on_conflict_do_nothing(index_elements=["user_id", "usage_date"])
    )
    await db.execute(insert_stmt)
    await db.flush()

    usage = await _query_usage(db, user_id, usage_date)
    if usage is None:  # pragma: no cover - defensive
        raise RuntimeError("Unable to create user_daily_llm_usage record")
    return usage


async def begin_daily_usage(
    db: AsyncSession, *, user: User, token_source: TokenSource = "system"
) -> Optional[DailyUsageHandle]:
    """Check quota before consuming tokens."""

    usage_date = utc_today()

    if token_source == "user":
        await _get_or_create_usage(db, user.id, usage_date)
        return DailyUsageHandle(
            user_id=user.id,
            usage_date=usage_date,
            token_source=token_source,
        )

    if not settings.enforce_user_token_limit or user.is_superuser:
        return None

    usage = await _get_or_create_usage(db, user.id, usage_date)
    limit = max(int(settings.user_daily_token_limit), 0)
    used = max(
        int(usage.system_tokens_total or 0),
        int(usage.tokens_total or 0),
    )

    if used >= limit:
        raise DailyTokenQuotaExceededError(
            limit=limit,
            used=used,
            reset_at=_reset_at(usage_date),
        )

    return DailyUsageHandle(
        user_id=user.id,
        usage_date=usage_date,
        token_source=token_source,
    )


async def finalize_daily_usage(
    db: AsyncSession,
    *,
    handle: Optional[DailyUsageHandle],
    tokens_delta: int,
    max_tokens_snapshot: Optional[int],
) -> Optional[UserDailyLlmUsage]:
    """Persist actual token consumption after completion."""

    if handle is None:
        return None

    usage = await _get_or_create_usage(db, handle.user_id, handle.usage_date)

    increment = max(int(tokens_delta or 0), 0)
    current_total = int(usage.tokens_total or 0)
    current_count = int(usage.request_count or 0)
    if handle.token_source == "user":
        usage.user_tokens_total = int(usage.user_tokens_total or 0) + increment
        usage.user_request_count = int(usage.user_request_count or 0) + 1
    else:
        usage.system_tokens_total = int(usage.system_tokens_total or 0) + increment
        usage.system_request_count = int(usage.system_request_count or 0) + 1

    usage.tokens_total = current_total + increment
    usage.request_count = current_count + 1
    if max_tokens_snapshot is not None:
        usage.max_tokens_snapshot = max_tokens_snapshot

    await db.flush()
    return usage


__all__ = [
    "DailyTokenQuotaExceededError",
    "DailyUsageHandle",
    "TokenSource",
    "_reset_at",
    "begin_daily_usage",
    "finalize_daily_usage",
]
