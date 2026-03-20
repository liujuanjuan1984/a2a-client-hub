from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from app.core.secret_vault import hub_a2a_secret_vault
from app.db.models.a2a_agent import A2AAgent
from app.services.a2a_runtime import a2a_runtime_builder
from app.services.hub_a2a_runtime import hub_a2a_runtime_builder


def test_a2a_runtime_builder_build_from_agent_uses_prefetched_fields() -> None:
    agent = A2AAgent(
        id=uuid4(),
        user_id=uuid4(),
        name="Personal Agent",
        card_url="https://personal.example.com",
        auth_type="none",
        extra_headers={"X-Test": "1"},
        enabled=True,
    )

    runtime = a2a_runtime_builder.build_from_agent(agent=agent, credential=None)

    assert runtime.agent is agent
    assert runtime.resolved.url == "https://personal.example.com"
    assert runtime.resolved.headers == {"X-Test": "1"}
    assert runtime.token_last4 is None


def test_hub_runtime_builder_resolve_prefetched_builds_bearer_headers() -> None:
    encrypted_token, token_last4 = hub_a2a_secret_vault.encrypt("shared-secret-token")
    credential = SimpleNamespace(
        encrypted_token=encrypted_token,
        token_last4=token_last4,
    )

    resolved, resolved_last4 = hub_a2a_runtime_builder.resolve_prefetched(
        name="Shared Agent",
        card_url="https://shared.example.com",
        extra_headers={"X-Shared": "1"},
        auth_type="bearer",
        auth_header=None,
        auth_scheme=None,
        credential=credential,
    )

    assert resolved.url == "https://shared.example.com"
    assert resolved.headers["X-Shared"] == "1"
    assert resolved.headers["Authorization"] == "Bearer shared-secret-token"
    assert resolved_last4 == token_last4
