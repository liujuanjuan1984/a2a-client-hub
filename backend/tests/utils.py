from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.db.models.dimension import Dimension
from app.db.models.food import Food
from app.db.models.person import Person
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.handlers import actual_event_quick_templates as quick_template_handlers
from app.handlers import auth as auth_handlers
from app.handlers import dimensions as dimension_handlers
from app.handlers import foods as foods_handlers
from app.handlers import persons as persons_handlers
from app.handlers import tasks as tasks_handlers
from app.handlers import visions as vision_handlers
from app.handlers.user_onboarding import UserOnboardingService
from app.schemas.actual_event_quick_template import ActualEventQuickTemplateCreate
from app.schemas.dimension import DimensionCreate
from app.schemas.food import FoodCreate
from app.schemas.person import PersonCreate
from app.schemas.task import TaskCreate, TaskStatusUpdate
from app.schemas.vision import VisionCreate

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
    """Create a user via auth handler to reuse onboarding + validation logic."""

    onboarding_original = UserOnboardingService.create_default_data_for_user
    onboarding_disabled = False
    if skip_onboarding_defaults:
        onboarding_disabled = True

        async def _noop_onboarding(db, user):
            return None

        UserOnboardingService.create_default_data_for_user = _noop_onboarding  # type: ignore[assignment]

    try:
        result = await auth_handlers.register_user(
            session,
            email=email or f"user_{uuid4().hex[:8]}@example.com",
            name=name,
            password=password or DEFAULT_TEST_PASSWORD,
            timezone=timezone,
        )
    finally:
        if onboarding_disabled:
            UserOnboardingService.create_default_data_for_user = onboarding_original  # type: ignore[assignment]
    user = result.user

    # Handlers会将首个用户自动提升为超级管理员，但测试需要显式控制权限，
    # 因此根据调用方参数强制同步 is_superuser 状态。
    if is_superuser and not user.is_superuser:
        user.is_superuser = True
        await session.commit()
        await session.refresh(user)
    elif not is_superuser and user.is_superuser:
        user.is_superuser = False
        await session.commit()
        await session.refresh(user)

    if skip_onboarding_defaults and not onboarding_disabled:
        await _purge_onboarding_defaults(session, user.id)

    return user


async def _purge_onboarding_defaults(session: AsyncSession, user_id: UUID) -> None:
    """Remove default onboarding artifacts so tests can control initial state."""

    await session.execute(delete(Vision).where(Vision.user_id == user_id))
    await session.execute(delete(Dimension).where(Dimension.user_id == user_id))
    await session.execute(
        delete(UserPreference).where(
            UserPreference.user_id == user_id,
            UserPreference.key.in_(
                ["todos.default_inbox_vision", "dashboard.dimension_order"]
            ),
        )
    )
    await session.commit()


async def create_dimension(
    session: AsyncSession,
    user: User,
    *,
    name: Optional[str] = None,
    color: str = "#3B82F6",
    is_active: bool = True,
    display_order: int = 0,
) -> Dimension:
    payload = DimensionCreate(
        name=name or f"Dimension {uuid4().hex[:6]}",
        color=color,
        is_active=is_active,
        display_order=display_order,
    )
    return await dimension_handlers.create_dimension(
        session,
        user_id=user.id,
        dimension_in=payload,
    )


async def create_vision(
    session: AsyncSession,
    user: User,
    *,
    name: Optional[str] = None,
    description: str = "Test vision",
    dimension: Optional[Dimension] = None,
) -> Vision:
    payload = VisionCreate(
        name=name or f"Vision {uuid4().hex[:6]}",
        description=description,
        dimension_id=dimension.id if dimension else None,
    )
    return await vision_handlers.create_vision(
        session,
        user_id=user.id,
        vision_in=payload,
    )


async def create_task(
    session: AsyncSession,
    user: User,
    vision: Vision,
    *,
    content: Optional[str] = None,
    status: str = "todo",
    parent: Optional[Task] = None,
) -> Task:
    payload = TaskCreate(
        content=content or f"Task {uuid4().hex[:6]}",
        vision_id=vision.id,
        parent_task_id=parent.id if parent else None,
    )
    task = await tasks_handlers.create_task(
        session,
        user_id=user.id,
        task_data=payload,
    )

    if status and status != task.status:
        task = await tasks_handlers.update_task_status(
            session,
            user_id=user.id,
            task_id=task.id,
            status_data=TaskStatusUpdate(status=status),
        )

    return task


async def create_person(
    session: AsyncSession,
    user: User,
    *,
    name: Optional[str] = None,
) -> Person:
    payload = PersonCreate(name=name or f"Person {uuid4().hex[:6]}")
    return await persons_handlers.create_person(
        session,
        user_id=user.id,
        person_in=payload,
    )


async def create_actual_event_template(
    session: AsyncSession,
    user: User,
    *,
    title: Optional[str] = None,
    position: int = 0,
    dimension_id: Optional[UUID] = None,
    person_ids: Optional[List[UUID]] = None,
    default_duration_minutes: Optional[int] = None,
    usage_count: int = 0,
) -> ActualEventQuickTemplate:
    payload = ActualEventQuickTemplateCreate(
        title=title or f"Template {uuid4().hex[:6]}",
        position=position,
        dimension_id=dimension_id,
        person_ids=person_ids,
        default_duration_minutes=default_duration_minutes,
        usage_count=usage_count,
    )
    return await quick_template_handlers.create_template(
        session,
        user_id=user.id,
        template_in=payload,
    )


async def create_food(
    session: AsyncSession,
    *,
    name: Optional[str] = None,
    user: Optional[User] = None,
    is_common: Optional[bool] = None,
    calories_per_100g: float = 200.0,
    protein_per_100g: float = 10.0,
    carbs_per_100g: float = 20.0,
    fat_per_100g: float = 5.0,
    fiber_per_100g: float = 2.0,
    sugar_per_100g: float = 5.0,
    sodium_per_100g: float = 50.0,
) -> Food:
    if user is None:
        raise ValueError(
            "create_food now requires a user to persist ownership context."
        )

    payload = FoodCreate(
        name=name or f"Food {uuid4().hex[:6]}",
        is_common=is_common if is_common is not None else False,
        calories_per_100g=calories_per_100g,
        protein_per_100g=protein_per_100g,
        carbs_per_100g=carbs_per_100g,
        fat_per_100g=fat_per_100g,
        fiber_per_100g=fiber_per_100g,
        sugar_per_100g=sugar_per_100g,
        sodium_per_100g=sodium_per_100g,
    )
    return await foods_handlers.create_food(
        session,
        user_id=user.id,
        food_in=payload,
    )


def future_date(days: int = 1) -> date:
    """Utility to obtain a future date relative to today."""
    return date.today() + timedelta(days=days)


def combine_date_time(d: date, hour: int, minute: int = 0) -> datetime:
    """Helper to produce naive datetime for supplied date/time."""
    return datetime(d.year, d.month, d.day, hour, minute)
