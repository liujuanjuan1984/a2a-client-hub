import pytest

from app.api.routers import notifications as notifications_router
from app.services import notifications as notification_service
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_notifications_list_and_mark_read(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    first_message_ids = await notification_service.send_notification(
        async_db_session,
        user_ids=[user.id],
        body="First notice",
        title="First",
    )
    await notification_service.send_notification(
        async_db_session,
        user_ids=[user.id],
        body="Second notice",
        title="Second",
    )

    async with create_test_client(
        notifications_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get("/notifications/system")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pagination"]["total"] == 2
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["size"] == 20
        assert data["meta"]["unread_count"] == 2
        assert [item["body"] for item in data["items"]] == [
            "Second notice",
            "First notice",
        ]

        mark_resp = await client.post(
            "/notifications/system/mark-read",
            json={"message_ids": [str(first_message_ids[0])]},
        )
        assert mark_resp.status_code == 200
        mark_data = mark_resp.json()
        assert mark_data["updated"] == 1
        assert mark_data["unread_count"] == 1

        resp_after = await client.get("/notifications/system")
        data_after = resp_after.json()
        assert data_after["meta"]["unread_count"] == 1
        assert data_after["items"][1]["unread"] is False
        assert data_after["items"][0]["unread"] is True

        mark_all_resp = await client.post(
            "/notifications/system/mark-read",
            json={"mark_all": True},
        )
        assert mark_all_resp.status_code == 200
        mark_all_data = mark_all_resp.json()
        assert mark_all_data["updated"] == 1
        assert mark_all_data["unread_count"] == 0

        count_resp = await client.get("/notifications/system/unread-count")
        assert count_resp.status_code == 200
        assert count_resp.json()["unread_count"] == 0


async def test_notifications_endpoints_handle_missing_session(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        notifications_router.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        resp = await client.get("/notifications/system")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "items": [],
            "pagination": {"page": 1, "size": 20, "total": 0, "pages": 0},
            "meta": {"unread_count": 0},
        }

        count_resp = await client.get("/notifications/system/unread-count")
        assert count_resp.status_code == 200
        assert count_resp.json() == {"unread_count": 0}

        mark_resp = await client.post(
            "/notifications/system/mark-read",
            json={"mark_all": True},
        )
        assert mark_resp.status_code == 200
        assert mark_resp.json() == {"updated": 0, "unread_count": 0}
