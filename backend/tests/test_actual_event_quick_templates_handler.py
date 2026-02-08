from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.handlers import actual_event_quick_templates as templates_service
from app.handlers.actual_event_quick_templates import (
    ActualEventQuickTemplateAlreadyExistsError,
    ActualEventQuickTemplateNotFoundError,
)
from app.schemas.actual_event_quick_template import (
    ActualEventQuickTemplateCreate,
    ActualEventQuickTemplateUpdate,
)
from app.utils.timezone_util import utc_now
from backend.tests.utils import create_actual_event_template, create_person, create_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.usefixtures("engine"),
]


async def _create_template(async_db_session, **kwargs):
    return await templates_service.create_template(async_db_session, **kwargs)


async def _update_template(async_db_session, **kwargs):
    return await templates_service.update_template(async_db_session, **kwargs)


async def _reorder_templates(async_db_session, **kwargs):
    return await templates_service.reorder_templates(async_db_session, **kwargs)


async def _delete_template(async_db_session, **kwargs):
    return await templates_service.delete_template(async_db_session, **kwargs)


async def _bump_template_usage(async_db_session, **kwargs):
    return await templates_service.bump_template_usage(async_db_session, **kwargs)


async def _list_templates(async_db_session, **kwargs):
    return await templates_service.list_templates(async_db_session, **kwargs)


async def test_create_template_enforces_unique_title(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    await _create_template(
        async_db_session,
        user_id=user.id,
        template_in=ActualEventQuickTemplateCreate(title="Focus Block"),
    )

    with pytest.raises(ActualEventQuickTemplateAlreadyExistsError):
        await _create_template(
            async_db_session,
            user_id=user.id,
            template_in=ActualEventQuickTemplateCreate(title="focus block"),
        )


async def test_create_template_appends_position(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    first = await _create_template(
        async_db_session,
        user_id=user.id,
        template_in=ActualEventQuickTemplateCreate(title="Deep Work"),
    )
    second = await _create_template(
        async_db_session,
        user_id=user.id,
        template_in=ActualEventQuickTemplateCreate(title="Daily Review"),
    )

    assert second.position == first.position + 1


async def test_create_template_with_persons(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person_a = await create_person(async_db_session, user=user)
    person_b = await create_person(async_db_session, user=user)

    template = await _create_template(
        async_db_session,
        user_id=user.id,
        template_in=ActualEventQuickTemplateCreate(
            title="Pair Programming",
            person_ids=[person_a.id, person_b.id],
        ),
    )

    assert {p.id for p in template.persons} == {person_a.id, person_b.id}
    assert set(template.person_ids) == {person_a.id, person_b.id}


async def test_update_template_replaces_persons(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    person_a = await create_person(async_db_session, user=user)
    person_b = await create_person(async_db_session, user=user)
    person_c = await create_person(async_db_session, user=user)

    template = await _create_template(
        async_db_session,
        user_id=user.id,
        template_in=ActualEventQuickTemplateCreate(
            title="Daily Sync",
            person_ids=[person_a.id],
        ),
    )

    updated = await _update_template(
        async_db_session,
        user_id=user.id,
        template_id=template.id,
        update_in=ActualEventQuickTemplateUpdate(
            person_ids=[person_b.id, person_c.id],
        ),
    )

    assert {p.id for p in updated.persons} == {person_b.id, person_c.id}
    assert set(updated.person_ids) == {person_b.id, person_c.id}


async def test_update_template_allows_title_change(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    existing = await create_actual_event_template(
        async_db_session, user=user, title="Morning Routine", position=1
    )

    updated = await _update_template(
        async_db_session,
        user_id=user.id,
        template_id=existing.id,
        update_in=ActualEventQuickTemplateUpdate(
            title="Evening Routine",
            default_duration_minutes=90,
        ),
    )

    assert updated.title == "Evening Routine"
    assert updated.title_normalized == "evening routine"
    assert updated.default_duration_minutes == 90


async def test_update_template_rejects_duplicate_title(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await create_actual_event_template(
        async_db_session, user=user, title="Plan", position=1
    )
    second = await create_actual_event_template(
        async_db_session, user=user, title="Reflect", position=2
    )

    with pytest.raises(ActualEventQuickTemplateAlreadyExistsError):
        await _update_template(
            async_db_session,
            user_id=user.id,
            template_id=second.id,
            update_in=ActualEventQuickTemplateUpdate(title="plan"),
        )

    await async_db_session.refresh(second)
    assert second.title == "Reflect"


async def test_reorder_templates_updates_positions(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    a = await create_actual_event_template(
        async_db_session, user=user, title="A", position=0
    )
    b = await create_actual_event_template(
        async_db_session, user=user, title="B", position=1
    )
    c = await create_actual_event_template(
        async_db_session, user=user, title="C", position=2
    )

    await _reorder_templates(
        async_db_session,
        user_id=user.id,
        order_pairs=[
            (a.id, 2),
            (b.id, 0),
            (c.id, 1),
        ],
    )

    await async_db_session.refresh(a)
    await async_db_session.refresh(b)
    await async_db_session.refresh(c)
    assert (a.position, b.position, c.position) == (2, 0, 1)


async def test_reorder_templates_validates_ids(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    await create_actual_event_template(
        async_db_session, user=user, title="Solo", position=0
    )

    fake_id = uuid4()

    with pytest.raises(ActualEventQuickTemplateNotFoundError):
        await _reorder_templates(
            async_db_session,
            user_id=user.id,
            order_pairs=[(fake_id, 5)],
        )


async def test_delete_template_marks_soft_deleted(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    template = await create_actual_event_template(
        async_db_session, user=user, title="Archive", position=0
    )

    await _delete_template(async_db_session, user_id=user.id, template_id=template.id)

    result = await async_db_session.execute(
        select(ActualEventQuickTemplate).where(
            ActualEventQuickTemplate.id == template.id
        )
    )
    with_deleted = result.scalars().first()
    assert with_deleted is not None
    assert with_deleted.deleted_at is not None


async def test_bump_template_usage_increments_counter(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    template = await create_actual_event_template(
        async_db_session, user=user, title="Call", position=1
    )

    before_usage = template.usage_count
    now = utc_now()
    bumped = await _bump_template_usage(
        async_db_session,
        user_id=user.id,
        template_id=template.id,
        when=now,
    )

    assert bumped.usage_count == before_usage + 1
    assert bumped.last_used_at == now


async def test_list_templates_returns_pagination(async_db_session):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)
    for idx in range(3):
        await create_actual_event_template(
            async_db_session, user=user, title=f"Template {idx}", position=idx
        )

    items, total = await _list_templates(
        async_db_session, user_id=user.id, limit=2, offset=0
    )

    assert total == 3
    assert len(items) == 2
    assert items[0].position == 0
