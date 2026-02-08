from datetime import date

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models.user_daily_llm_usage import UserDailyLlmUsage
from app.services import token_quota_service
from app.services.token_quota_service import DailyTokenQuotaExceededError
from backend.tests.utils import create_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fixed_date():
    return date(2025, 1, 1)


async def test_begin_daily_usage_blocks_when_limit_reached(
    async_db_session, async_session_maker, monkeypatch, fixed_date
):
    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )
    record = UserDailyLlmUsage(
        user_id=user.id,
        usage_date=fixed_date,
        tokens_total=settings.user_daily_token_limit,
        system_tokens_total=settings.user_daily_token_limit,
    )
    async_db_session.add(record)
    await async_db_session.commit()

    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today",
        lambda: fixed_date,
    )

    async with async_session_maker() as session:
        with pytest.raises(DailyTokenQuotaExceededError):
            await token_quota_service.begin_daily_usage(session, user=user)


async def test_finalize_daily_usage_accumulates_tokens(
    async_db_session, async_session_maker, monkeypatch, fixed_date
):
    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )
    await async_db_session.commit()

    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today",
        lambda: fixed_date,
    )

    async with async_session_maker() as session:
        handle = await token_quota_service.begin_daily_usage(session, user=user)
        assert handle is not None

        await token_quota_service.finalize_daily_usage(
            session,
            handle=handle,
            tokens_delta=321,
            max_tokens_snapshot=4096,
        )

        result = await session.execute(
            select(UserDailyLlmUsage).where(
                UserDailyLlmUsage.user_id == user.id,
                UserDailyLlmUsage.usage_date == fixed_date,
            )
        )
        usage = result.scalar_one()

        assert usage.tokens_total == 321
        assert usage.system_tokens_total == 321
        assert usage.system_request_count == 1
        assert usage.user_tokens_total == 0
        assert usage.user_request_count == 0
        assert usage.request_count == 1
        assert usage.max_tokens_snapshot == 4096


async def test_begin_daily_usage_skips_admin(
    async_db_session, async_session_maker, monkeypatch, fixed_date
):
    admin = await create_user(
        async_db_session, is_superuser=True, skip_onboarding_defaults=True
    )
    await async_db_session.commit()
    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today",
        lambda: fixed_date,
    )

    async with async_session_maker() as session:
        handle = await token_quota_service.begin_daily_usage(session, user=admin)
        assert handle is None

        # 完成阶段应静默返回
        assert (
            await token_quota_service.finalize_daily_usage(
                session,
                handle=handle,
                tokens_delta=100,
                max_tokens_snapshot=1024,
            )
            is None
        )


async def test_user_token_usage_bypasses_quota(
    async_db_session, async_session_maker, monkeypatch, fixed_date
):
    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )
    record = UserDailyLlmUsage(
        user_id=user.id,
        usage_date=fixed_date,
        tokens_total=settings.user_daily_token_limit,
        system_tokens_total=settings.user_daily_token_limit,
    )
    async_db_session.add(record)
    await async_db_session.commit()

    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today",
        lambda: fixed_date,
    )

    # Should not raise even though system limit reached
    async with async_session_maker() as session:
        handle = await token_quota_service.begin_daily_usage(
            session, user=user, token_source="user"
        )
        assert handle is not None

        await token_quota_service.finalize_daily_usage(
            session,
            handle=handle,
            tokens_delta=500,
            max_tokens_snapshot=None,
        )

        result = await session.execute(
            select(UserDailyLlmUsage).where(
                UserDailyLlmUsage.user_id == user.id,
                UserDailyLlmUsage.usage_date == fixed_date,
            )
        )
        usage = result.scalar_one()

        assert usage.system_tokens_total == settings.user_daily_token_limit
        assert usage.user_tokens_total == 500
        assert usage.tokens_total == settings.user_daily_token_limit + 500
        assert usage.user_request_count == 1
