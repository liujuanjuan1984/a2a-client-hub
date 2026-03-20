import pytest

from app.db.models.a2a_agent import A2AAgent
from app.features.shortcuts import router as shortcuts
from tests.api_utils import create_test_client
from tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_shortcuts_agent_specific_features(async_db_session, async_session_maker):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    agent1 = A2AAgent(
        user_id=user.id,
        name="Agent 1",
        card_url="http://agent1.local",
        agent_scope=A2AAgent.SCOPE_PERSONAL,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    agent2 = A2AAgent(
        user_id=user.id,
        name="Agent 2",
        card_url="http://agent2.local",
        agent_scope=A2AAgent.SCOPE_PERSONAL,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
    )
    async_db_session.add_all([agent1, agent2])
    await async_db_session.flush()
    await async_db_session.commit()

    agent1_id = str(agent1.id)
    agent2_id = str(agent2.id)

    async with create_test_client(
        shortcuts.router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        # Create general shortcut
        resp_gen = await client.post(
            "/me/shortcuts",
            json={"title": "General", "prompt": "Gen Prompt"},
        )
        assert resp_gen.status_code == 201
        shortcut_gen = resp_gen.json()
        assert shortcut_gen["agent_id"] is None

        # Create agent 1 shortcut
        resp_a1 = await client.post(
            "/me/shortcuts",
            json={"title": "A1", "prompt": "A1 Prompt", "agent_id": agent1_id},
        )
        assert resp_a1.status_code == 201
        shortcut_a1 = resp_a1.json()
        assert shortcut_a1["agent_id"] == agent1_id

        # List with no agent_id - should return ALL shortcuts (5 default + 2 custom)
        resp_list_all = await client.get("/me/shortcuts")
        all_items = resp_list_all.json()["items"]
        assert len(all_items) == 7

        # List with agent1_id - should return 5 default + general + a1
        resp_list_a1 = await client.get(f"/me/shortcuts?agent_id={agent1_id}")
        a1_items = resp_list_a1.json()["items"]
        assert len(a1_items) == 7
        assert any(item["title"] == "A1" for item in a1_items)
        assert any(item["title"] == "General" for item in a1_items)

        # List with agent2_id - should return 5 default + general (NO a1)
        resp_list_a2_initial = await client.get(f"/me/shortcuts?agent_id={agent2_id}")
        a2_initial_items = resp_list_a2_initial.json()["items"]
        assert len(a2_initial_items) == 6
        assert any(item["title"] == "General" for item in a2_initial_items)
        assert not any(item["title"] == "A1" for item in a2_initial_items)

        # Update a1 shortcut to be general
        resp_update = await client.patch(
            f"/me/shortcuts/{shortcut_a1['id']}",
            json={"clear_agent": True},
        )
        assert resp_update.status_code == 200
        assert resp_update.json()["agent_id"] is None

        # Verify it became general
        resp_list_a2 = await client.get(f"/me/shortcuts?agent_id={agent2_id}")
        a2_items = resp_list_a2.json()["items"]
        assert any(
            item["title"] == "A1" for item in a2_items
        )  # It's now general, so a2 sees it

        # Update general shortcut to specific agent2
        resp_update2 = await client.patch(
            f"/me/shortcuts/{shortcut_gen['id']}",
            json={"agent_id": agent2_id},
        )
        assert resp_update2.status_code == 200
        assert resp_update2.json()["agent_id"] == agent2_id
