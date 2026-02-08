from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agents.chat_service import ChatServiceError, chat_service
from app.core.config import settings
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.db.models.user_daily_llm_usage import UserDailyLlmUsage
from app.services.token_quota_service import DailyTokenQuotaExceededError
from backend.tests.utils import create_user


@pytest.mark.asyncio
async def test_get_chat_history_returns_latest_messages(async_session_maker):
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    async with async_session_maker() as session:
        user = await create_user(session, skip_onboarding_defaults=True)
        chat_session = AgentSession(
            id=uuid4(),
            user_id=user.id,
            name="System Notifications",
            session_type=AgentSession.TYPE_SYSTEM,
        )
        session.add(chat_session)
        await session.flush()
        for index in range(60):
            timestamp = base_time + timedelta(minutes=index)
            message = AgentMessage(
                user_id=user.id,
                session_id=chat_session.id,
                content=f"message-{index}",
                sender="system",
                message_type=AgentMessage.TYPE_NOTIFICATION,
                severity=AgentMessage.SEVERITY_INFO,
            )
            message.created_at = timestamp
            message.updated_at = timestamp
            session.add(message)
        await session.flush()

        messages, total = await chat_service.get_chat_history(
            db=session,
            user_id=user.id,
            limit=50,
            offset=0,
            session_id=chat_session.id,
        )

    assert total == 60
    assert len(messages) == 50
    assert messages[0].content == "message-10"
    assert messages[-1].content == "message-59"


@pytest.mark.asyncio
async def test_send_message_records_daily_usage(async_db_session, monkeypatch):
    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )

    async def fake_generate_response(*args, **kwargs):
        return SimpleNamespace(
            content="hi",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            cost_usd=None,
            response_time_ms=120,
            model_name="gpt-test",
            context_token_usage=None,
            context_window_tokens=None,
            context_budget_tokens=None,
            context_messages_selected=None,
            context_messages_dropped=None,
            context_box_messages_selected=None,
            context_box_messages_dropped=None,
            tool_runs=[],
        )

    monkeypatch.setattr(
        chat_service.agent_service,
        "generate_response_with_tools",
        fake_generate_response,
    )
    monkeypatch.setattr(
        "app.cardbox.service.cardbox_service.sync_message",
        lambda *args, **kwargs: None,
    )

    async def fake_overview_background(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.agents.chat_service.ChatService._update_overview_background",
        fake_overview_background,
    )

    await chat_service.send_message(
        db=async_db_session,
        user=user,
        content="ping",
    )

    stmt = select(UserDailyLlmUsage).where(UserDailyLlmUsage.user_id == user.id)
    usage_rows = (await async_db_session.execute(stmt)).scalars().all()
    assert len(usage_rows) == 1
    assert usage_rows[0].tokens_total == 15
    assert usage_rows[0].request_count == 1
    assert usage_rows[0].max_tokens_snapshot == settings.litellm_completion_max_tokens


@pytest.mark.asyncio
async def test_send_message_raises_when_daily_limit_reached(
    async_db_session, monkeypatch
):
    fixed_usage_date = date(2025, 1, 1)

    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )
    async_db_session.add(
        UserDailyLlmUsage(
            user_id=user.id,
            usage_date=fixed_usage_date,
            tokens_total=settings.user_daily_token_limit,
        )
    )
    await async_db_session.flush()

    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today",
        lambda: fixed_usage_date,
    )

    with pytest.raises(DailyTokenQuotaExceededError):
        await chat_service.send_message(
            db=async_db_session,
            user=user,
            content="hello",
        )


@pytest.mark.asyncio
async def test_get_chat_history_returns_paginated_messages(async_db_session):
    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)

    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    chat_session = AgentSession(
        id=uuid4(),
        user_id=user.id,
        name="Async History",
        session_type=AgentSession.TYPE_CHAT,
    )
    async_db_session.add(chat_session)
    await async_db_session.flush()
    for index in range(4):
        timestamp = base_time + timedelta(minutes=index)
        message = AgentMessage(
            user_id=user.id,
            session_id=chat_session.id,
            content=f"event-{index}",
            sender="system" if index % 2 == 0 else "user",
            message_type=AgentMessage.TYPE_NOTIFICATION,
            severity=AgentMessage.SEVERITY_INFO,
        )
        message.created_at = timestamp
        message.updated_at = timestamp
        async_db_session.add(message)

    await async_db_session.flush()
    messages, total = await chat_service.get_chat_history(
        db=async_db_session,
        user_id=user.id,
        limit=3,
        offset=1,
        session_id=chat_session.id,
    )

    assert total == 4
    assert [msg.content for msg in messages] == ["event-0", "event-1", "event-2"]


@pytest.mark.asyncio
async def test_send_message_respects_token_quota(async_db_session, monkeypatch):
    limit_date = date(2025, 1, 1)

    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )
    stmt = select(UserDailyLlmUsage).where(
        UserDailyLlmUsage.user_id == user.id,
        UserDailyLlmUsage.usage_date == limit_date,
    )
    usage = (await async_db_session.execute(stmt)).scalars().one_or_none()
    if usage is None:
        usage = UserDailyLlmUsage(
            user_id=user.id,
            usage_date=limit_date,
            tokens_total=settings.user_daily_token_limit,
        )
        async_db_session.add(usage)
    else:
        usage.tokens_total = settings.user_daily_token_limit
    await async_db_session.flush()

    monkeypatch.setattr(
        "app.services.token_quota_service.utc_today", lambda: limit_date
    )

    with pytest.raises(DailyTokenQuotaExceededError):
        await chat_service.send_message(
            db=async_db_session,
            user=user,
            content="async hello",
        )

    remaining = await async_db_session.scalar(
        select(func.count()).select_from(AgentMessage)
    )
    assert remaining == 0


@pytest.mark.asyncio
async def test_send_message_rolls_back_on_agent_failure(async_db_session, monkeypatch):
    user = await create_user(
        async_db_session, is_superuser=False, skip_onboarding_defaults=True
    )

    def failing_response(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(
        chat_service.agent_service,
        "generate_response_with_tools",
        failing_response,
    )
    monkeypatch.setattr(
        "app.cardbox.service.cardbox_service.sync_message",
        lambda *args, **kwargs: None,
    )

    async def noop_overview(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "app.agents.chat_service.ChatService._update_overview_background",
        noop_overview,
    )

    with pytest.raises(ChatServiceError):
        await chat_service.send_message(
            db=async_db_session,
            user=user,
            content="async fail",
        )

    remaining = await async_db_session.scalar(
        select(func.count()).select_from(AgentMessage)
    )
    assert remaining == 0
