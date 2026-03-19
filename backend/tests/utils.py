from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.user import User

DEFAULT_TEST_PASSWORD = "Password123!"


async def create_user(
    session: AsyncSession,
    email: Optional[str] = None,
    name: str = "Test User",
    *,
    is_superuser: bool = False,
    password: Optional[str] = None,
    timezone: str = "UTC",
    skip_onboarding_defaults: bool = False,
) -> User:
    # `skip_onboarding_defaults` is kept for backward compatibility with the
    # upstream test suite. The A2A client backend cut does not run onboarding.
    _ = skip_onboarding_defaults

    user = User(
        email=email or f"user_{uuid4().hex[:8]}@example.com",
        name=name,
        password_hash=get_password_hash(password or DEFAULT_TEST_PASSWORD),
        is_superuser=is_superuser,
        timezone=timezone,
    )
    session.add(user)
    await session.flush()
    await session.commit()
    await session.refresh(user)
    return user


async def create_a2a_agent(
    session: AsyncSession,
    *,
    user_id,
    suffix: str = "test",
    name: str | None = None,
    card_url: str | None = None,
    auth_type: str = "none",
    enabled: bool = True,
) -> A2AAgent:
    agent = A2AAgent(
        user_id=user_id,
        name=name or f"Agent {suffix}",
        card_url=card_url or f"https://example.com/{suffix}",
        auth_type=auth_type,
        enabled=enabled,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def create_schedule_task(
    session: AsyncSession,
    *,
    user_id,
    agent_id,
    enabled: bool = True,
    next_run_at: datetime | None = None,
    name: str = "Test schedule",
    prompt: str = "hello",
    cycle_type: str = A2AScheduleTask.CYCLE_DAILY,
    time_point: dict[str, object] | None = None,
    conversation_id=None,
    conversation_policy: str = A2AScheduleTask.POLICY_NEW,
    consecutive_failures: int = 0,
) -> A2AScheduleTask:
    task = A2AScheduleTask(
        user_id=user_id,
        name=name,
        agent_id=agent_id,
        prompt=prompt,
        cycle_type=cycle_type,
        time_point=time_point or {"time": "09:00"},
        enabled=enabled,
        next_run_at=next_run_at,
        conversation_id=conversation_id,
        conversation_policy=conversation_policy,
        consecutive_failures=consecutive_failures,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task
