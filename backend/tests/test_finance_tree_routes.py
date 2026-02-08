from __future__ import annotations

import pytest

from app.api.routers.finance_accounts import router as accounts_router
from app.api.routers.finance_cashflow import router as cashflow_router
from backend.tests.api_utils import create_test_client
from backend.tests.utils import create_user

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _count_default(trees: list[dict]) -> int:
    return sum(1 for tree in trees if tree.get("is_default"))


async def test_account_tree_crud_and_default_switch(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        accounts_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/finance/accounts/trees")
        assert response.status_code == 200
        trees = response.json()
        assert len(trees) == 1
        assert trees[0]["is_default"] is True

        response = await client.post(
            "/finance/accounts/trees",
            json={"name": "Secondary Accounts"},
        )
        assert response.status_code == 201
        secondary_tree = response.json()
        assert secondary_tree["is_default"] is False

        response = await client.patch(
            f"/finance/accounts/trees/{secondary_tree['id']}",
            json={"is_default": True, "name": "Secondary Accounts Updated"},
        )
        assert response.status_code == 200

        response = await client.get("/finance/accounts/trees")
        assert response.status_code == 200
        trees = response.json()
        assert _count_default(trees) == 1
        assert any(
            tree["id"] == secondary_tree["id"] and tree["is_default"] is True
            for tree in trees
        )


async def test_account_tree_delete_guards_and_cross_tree_parent(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        accounts_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/finance/accounts/trees")
        assert response.status_code == 200
        default_tree_id = response.json()[0]["id"]

        response = await client.delete(f"/finance/accounts/trees/{default_tree_id}")
        assert response.status_code == 400

        response = await client.post(
            "/finance/accounts/trees",
            json={"name": "Alt Accounts"},
        )
        assert response.status_code == 201
        alt_tree_id = response.json()["id"]

        response = await client.post(
            "/finance/accounts/",
            json={
                "name": "Alt Root",
                "currency_code": "USD",
                "tree_id": alt_tree_id,
            },
        )
        assert response.status_code == 201

        response = await client.delete(f"/finance/accounts/trees/{alt_tree_id}")
        assert response.status_code == 400

        response = await client.post(
            "/finance/accounts/",
            json={
                "name": "Default Root",
                "currency_code": "USD",
                "tree_id": default_tree_id,
            },
        )
        assert response.status_code == 201
        parent_id = response.json()["id"]

        response = await client.post(
            "/finance/accounts/",
            json={
                "name": "Cross Tree Child",
                "currency_code": "USD",
                "parent_id": parent_id,
                "tree_id": alt_tree_id,
            },
        )
        assert response.status_code == 400


async def test_cashflow_tree_crud_and_default_switch(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        cashflow_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/finance/cashflow/trees")
        assert response.status_code == 200
        trees = response.json()
        assert len(trees) == 1
        assert trees[0]["is_default"] is True

        response = await client.post(
            "/finance/cashflow/trees",
            json={"name": "Secondary Sources"},
        )
        assert response.status_code == 201
        secondary_tree = response.json()
        assert secondary_tree["is_default"] is False

        response = await client.patch(
            f"/finance/cashflow/trees/{secondary_tree['id']}",
            json={"is_default": True, "name": "Secondary Sources Updated"},
        )
        assert response.status_code == 200

        response = await client.get("/finance/cashflow/trees")
        assert response.status_code == 200
        trees = response.json()
        assert _count_default(trees) == 1
        assert any(
            tree["id"] == secondary_tree["id"] and tree["is_default"] is True
            for tree in trees
        )


async def test_cashflow_tree_delete_guards_and_cross_tree_parent(
    async_db_session, async_session_maker
):
    user = await create_user(async_db_session, skip_onboarding_defaults=True)

    async with create_test_client(
        cashflow_router,
        async_session_maker=async_session_maker,
        current_user=user,
    ) as client:
        response = await client.get("/finance/cashflow/trees")
        assert response.status_code == 200
        default_tree_id = response.json()[0]["id"]

        response = await client.delete(f"/finance/cashflow/trees/{default_tree_id}")
        assert response.status_code == 400

        response = await client.post(
            "/finance/cashflow/trees",
            json={"name": "Alt Sources"},
        )
        assert response.status_code == 201
        alt_tree_id = response.json()["id"]

        response = await client.post(
            "/finance/cashflow/sources",
            json={"name": "Alt Root", "tree_id": alt_tree_id, "kind": "regular"},
        )
        assert response.status_code == 201

        response = await client.delete(f"/finance/cashflow/trees/{alt_tree_id}")
        assert response.status_code == 400

        response = await client.post(
            "/finance/cashflow/sources",
            json={
                "name": "Default Root",
                "tree_id": default_tree_id,
                "kind": "regular",
            },
        )
        assert response.status_code == 201
        parent_id = response.json()["id"]

        response = await client.post(
            "/finance/cashflow/sources",
            json={
                "name": "Cross Tree Child",
                "tree_id": alt_tree_id,
                "parent_id": parent_id,
                "kind": "regular",
            },
        )
        assert response.status_code == 404
