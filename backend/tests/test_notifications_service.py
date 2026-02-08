from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_receipt import AgentMessageReceipt
from app.db.models.agent_session import AgentSession
from app.services import notifications as notification_service
from app.utils.timezone_util import utc_now
from backend.tests.utils import create_user


@pytest.mark.asyncio
async def test_send_notification_creates_system_session_and_receipt(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with async_session_maker() as async_db:
        message_ids = await notification_service.send_notification(
            async_db,
            user_ids=[user.id],
            body="Work recalculation job failed",
            title="工作重算失败",
            severity=AgentMessage.SEVERITY_WARNING,
            metadata={"job_id": "test-job"},
        )

        assert len(message_ids) == 1

        session = await notification_service.get_system_session(
            async_db, user_id=user.id
        )
        assert session is not None
        assert session.session_type == AgentSession.TYPE_SYSTEM

        message = (
            await async_db.execute(
                select(AgentMessage).where(AgentMessage.id == message_ids[0])
            )
        ).scalar_one()
        assert message.message_type == AgentMessage.TYPE_NOTIFICATION
        assert message.severity == AgentMessage.SEVERITY_WARNING
        assert message.sender == "system"
        assert message.message_metadata["payload"]["job_id"] == "test-job"

        receipt = (
            await async_db.execute(
                select(AgentMessageReceipt).where(
                    AgentMessageReceipt.message_id == message.id
                )
            )
        ).scalar_one()
        assert receipt.read_at is None


@pytest.mark.asyncio
async def test_mark_notifications_read_updates_system_notifications(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with async_session_maker() as async_db:
        first_message = await notification_service.send_notification(
            async_db,
            user_ids=[user.id],
            body="First notification",
        )

        second_message = await notification_service.send_notification(
            async_db,
            user_ids=[user.id],
            body="Second notification",
        )

        session = await notification_service.get_system_session(
            async_db, user_id=user.id
        )
        assert session is not None

        total, rows = await notification_service.list_system_notifications(
            async_db,
            user_id=user.id,
            session_id=session.id,
        )
        assert total == 2
        assert {message.id for message, read_at in rows if read_at is None} == set(
            first_message + second_message
        )

        updated = await notification_service.mark_notifications_read(
            async_db, user_id=user.id, message_ids=first_message
        )
        assert updated == 1

        receipt = (
            await async_db.execute(
                select(AgentMessageReceipt).where(
                    AgentMessageReceipt.message_id == first_message[0]
                )
            )
        ).scalar_one()
        assert receipt.read_at is not None
        assert receipt.read_at <= utc_now()

        total_after, rows_after = await notification_service.list_system_notifications(
            async_db,
            user_id=user.id,
            session_id=session.id,
        )
        assert total_after == 2
        assert {
            message.id for message, read_at in rows_after if read_at is None
        } == set(second_message)

        unread_count = await notification_service.count_unread_system_notifications(
            async_db,
            user_id=user.id,
            session_id=session.id,
        )
        assert unread_count == 1
