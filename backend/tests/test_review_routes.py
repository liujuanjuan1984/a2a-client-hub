from __future__ import annotations

import asyncio

import pytest

from app.api.routers import review as review_router
from app.review.daily_review_service import DailyReviewResult, StrategyExecutionSummary
from backend.tests.api_utils import create_test_client
from backend.tests.conftest import _truncate_all_tables
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="module")
def review_test_users(async_session_maker, async_engine):
    async def _setup():
        async with async_session_maker() as session:
            user = await create_user(session, skip_onboarding_defaults=True)
            forbidden_user = await create_user(session, skip_onboarding_defaults=True)
            admin = await create_user(
                session, is_superuser=True, skip_onboarding_defaults=True
            )
            await session.commit()
            for obj in (user, forbidden_user, admin):
                await session.refresh(obj)
                session.expunge(obj)
            return {
                "user": user,
                "other_user": forbidden_user,
                "admin": admin,
            }

    state = asyncio.run(_setup())

    try:
        yield state
    finally:
        asyncio.run(_truncate_all_tables(async_engine))


def _make_result(status: str = "completed") -> DailyReviewResult:
    return DailyReviewResult(
        status=status,
        output_box="box",
        summaries=[
            StrategyExecutionSummary(
                stage="summary",
                card_id="card-1",
                content="content",
                metadata={"foo": "bar"},
            )
        ],
        error=None,
        chat_markdown="# Review",
        input_box="input",
    )


async def test_trigger_daily_review_success(
    monkeypatch, review_test_users, async_session_maker
):
    user = review_test_users["user"]

    captured = {}

    async def fake_run_daily_review(
        db, *, user_id, target_date, force, trigger_source, config=None
    ):
        captured["user_id"] = user_id
        captured["target_date"] = target_date
        return _make_result()

    monkeypatch.setattr(review_router, "run_daily_review", fake_run_daily_review)

    async with create_test_client(
        review_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post(
            "/agent/review/run",
            json={"date": "2025-09-01", "force": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["detail"]["status"] == "completed"
    assert captured["user_id"] == user.id
    assert captured["target_date"].isoformat() == "2025-09-01"


async def test_trigger_daily_review_forbidden_for_other_user(
    review_test_users, async_session_maker
):
    user = review_test_users["user"]

    async with create_test_client(
        review_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.post(
            "/agent/review/run",
            json={"user_id": str(review_test_users["other_user"].id)},
        )

    assert response.status_code == 403


async def test_trigger_daily_review_superuser_can_target_other_user(
    monkeypatch, review_test_users, async_session_maker
):
    admin = review_test_users["admin"]
    target_user = review_test_users["other_user"]

    async def fake_run_daily_review(
        db, *, user_id, target_date, force, trigger_source, config=None
    ):
        return _make_result()

    monkeypatch.setattr(review_router, "run_daily_review", fake_run_daily_review)

    async with create_test_client(
        review_router.router,
        async_session_maker=async_session_maker,
        current_user=admin,
    ) as client:
        response = await client.post(
            "/agent/review/run",
            json={"user_id": str(target_user.id)},
        )

    assert response.status_code == 200
