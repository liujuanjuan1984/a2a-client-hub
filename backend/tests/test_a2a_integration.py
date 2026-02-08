import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    TextPart,
    TransportProtocol,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from app.agents.tools.a2a_tool import A2AAgentTool
from app.agents.tools.responses import ToolResult
from app.core import config as app_config
from app.integrations.a2a_client.client import A2AClient
from app.integrations.a2a_client.config import A2AAgentConfig, A2ASettings
from app.integrations.a2a_client.errors import (
    A2AAgentUnavailableError,
    A2AClientResetRequiredError,
)
from app.integrations.a2a_client.gateway import A2AGateway
from app.integrations.a2a_client.service import A2AService, ResolvedAgent


@pytest.mark.asyncio
async def test_a2a_service_calls_agent(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
                headers={"Authorization": "Bearer token"},
            )
        },
    )
    service = A2AService(settings)
    captured_query = {}

    class DummyClient:
        def __init__(self, agent_url, **kwargs):
            self.agent_url = agent_url
            self.headers = kwargs.get("default_headers", {})
            self.interceptors = kwargs.get("interceptors", [])
            assert self.headers == {"Authorization": "Bearer token"}
            assert len(self.interceptors) == 1

        async def call_agent(self, query, context_id=None, metadata=None):
            captured_query["value"] = query
            return {"success": True, "content": f"echo:{query}"}

        async def get_agent_card(self):
            return SimpleNamespace(name="demo")

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", DummyClient)

    resolved = service.resolve_agent(agent="demo")
    result = await service.call_agent(resolved=resolved, query="ping")

    assert result["success"] is True
    assert captured_query["value"] == "ping"


@pytest.mark.asyncio
async def test_a2a_service_handles_unavailable_agent(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
                metadata={},
                headers={},
            )
        },
    )

    class TimeoutClient:
        instances = []

        def __init__(self, agent_url, **kwargs):
            self.agent_url = agent_url
            TimeoutClient.instances.append(self)

        async def get_agent_card(self):
            raise A2AAgentUnavailableError("timeout")

        async def call_agent(self, query, context_id=None, metadata=None):
            raise A2AAgentUnavailableError("timeout")

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", TimeoutClient)

    service = A2AService(settings)
    resolved = service.resolve_agent(agent="demo")

    with pytest.raises(A2AAgentUnavailableError):
        await service.gateway.fetch_agent_card(resolved=resolved, raise_on_failure=True)

    result = await service.call_agent(resolved=resolved, query="ping")

    assert result["success"] is False
    assert result["error_code"] == "agent_unavailable"


@pytest.mark.asyncio
async def test_a2a_gateway_reuses_clients(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
                metadata={},
                headers={},
            )
        },
    )

    close_calls = []

    class DummyClient:
        instances = 0

        def __init__(self, agent_url, **_kwargs):
            self.agent_url = agent_url
            DummyClient.instances += 1

        async def call_agent(self, query, context_id=None, metadata=None):
            return {"success": True, "content": query}

        async def get_agent_card(self):  # pragma: no cover - not used
            return SimpleNamespace(name="demo")

        async def close(self):
            close_calls.append(self.agent_url)

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", DummyClient)

    service = A2AService(settings)
    resolved = service.resolve_agent(agent="demo")

    await service.call_agent(resolved=resolved, query="first")
    await service.call_agent(resolved=resolved, query="second")

    assert DummyClient.instances == 1

    await service.gateway.shutdown()
    assert close_calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_a2a_gateway_maps_timeouts(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=0.1,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
                metadata={},
                headers={},
            )
        },
    )

    class SlowClient:
        def __init__(self, *_args, **_kwargs):
            return None

        async def call_agent(self, query, context_id=None, metadata=None):
            await asyncio.sleep(2)

        async def get_agent_card(self):
            return SimpleNamespace(name="demo")

        async def close(self):
            return None

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", SlowClient)

    service = A2AService(settings)
    resolved = service.resolve_agent(agent="demo")

    result = await service.call_agent(resolved=resolved, query="ping")

    assert result["success"] is False
    assert result["error_code"] == "timeout"


@pytest.mark.asyncio
async def test_a2a_agent_tool_success(async_db_session, monkeypatch):
    class DummyService:
        def __init__(self):
            self._resolved = None

        def is_enabled(self):
            return True

        def list_agents(self):  # pragma: no cover - not used
            return {"demo": A2AAgentConfig(url="https://example.com", name="demo")}

        def resolve_agent(self, agent=None, agent_url=None):
            assert agent == "demo"
            self._resolved = agent
            return ResolvedAgent(
                name="demo",
                url="https://example.com",
                description=None,
                metadata={},
                headers={},
            )

        async def call_agent(self, resolved, query, context_id=None, metadata=None):
            assert query == "ping"
            return {
                "success": True,
                "content": "pong",
                "agent_url": "https://example.com",
            }

    service = DummyService()

    monkeypatch.setattr("app.agents.tools.a2a_tool.get_a2a_service", lambda: service)
    monkeypatch.setattr(app_config.settings, "a2a_enabled", True)

    tool = A2AAgentTool(db=async_db_session, user_id=uuid4())
    result = await tool.execute(agent="demo", query="ping")

    assert isinstance(result, ToolResult)
    assert result.status == "success"
    assert result.data["agent_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_a2a_agent_tool_unavailable_maps_error(async_db_session, monkeypatch):
    class DummyService:
        def is_enabled(self):
            return True

        def resolve_agent(self, agent=None, agent_url=None):
            return ResolvedAgent(
                name="demo",
                url="https://example.com",
                description=None,
                metadata={},
                headers={},
            )

        async def call_agent(self, resolved, query, context_id=None, metadata=None):
            return {
                "success": False,
                "error": "A2A agent 'demo' timed out while fetching metadata",
                "error_code": "agent_unavailable",
            }

    monkeypatch.setattr(
        "app.agents.tools.a2a_tool.get_a2a_service", lambda: DummyService()
    )
    monkeypatch.setattr(app_config.settings, "a2a_enabled", True)

    tool = A2AAgentTool(db=async_db_session, user_id=uuid4())
    result = await tool.execute(agent="demo", query="ping")

    assert result.status == "error"
    assert result.error_category == "a2a_unavailable"


@pytest.mark.asyncio
async def test_a2a_agent_tool_disabled(async_db_session, monkeypatch):
    monkeypatch.setattr(app_config.settings, "a2a_enabled", False)
    tool = A2AAgentTool(db=async_db_session, user_id=uuid4())
    result = await tool.execute(agent="demo", query="ping")
    assert result.status == "error"
    assert result.error_category == "a2a_disabled"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_a2a_gateway_resets_client_on_transport_error(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
            )
        },
        client_idle_timeout=600.0,
    )

    close_calls = []

    class FlakyClient:
        instances = 0
        fail_once = True

        def __init__(self, agent_url, **_kwargs):
            self.agent_url = agent_url
            FlakyClient.instances += 1

        async def call_agent(self, query, context_id=None, metadata=None):
            if FlakyClient.fail_once:
                FlakyClient.fail_once = False
                raise A2AClientResetRequiredError("reset")
            return {"success": True, "content": query}

        async def get_agent_card(self):
            return SimpleNamespace(name="demo")

        async def close(self):
            close_calls.append(self.agent_url)

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", FlakyClient)

    service = A2AService(settings)
    resolved = service.resolve_agent(agent="demo")

    result = await service.call_agent(resolved=resolved, query="ping")
    assert result["success"] is False
    assert result["error_code"] == "client_reset"

    second = await service.call_agent(resolved=resolved, query="pong")
    assert second["success"] is True
    assert FlakyClient.instances == 2
    assert close_calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_a2a_gateway_evicts_idle_clients(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
            )
        },
        client_idle_timeout=0.01,
    )

    close_calls = []

    class DummyClient:
        instances = 0

        def __init__(self, agent_url, **_kwargs):
            DummyClient.instances += 1
            self.agent_url = agent_url

        async def call_agent(self, query, context_id=None, metadata=None):
            return {"success": True, "content": query}

        async def get_agent_card(self):
            return SimpleNamespace(name="demo")

        async def close(self):
            close_calls.append(self.agent_url)

    monkeypatch.setattr("app.integrations.a2a_client.gateway.A2AClient", DummyClient)

    service = A2AService(settings)
    resolved = service.resolve_agent(agent="demo")

    await service.call_agent(resolved=resolved, query="first")

    gateway = service.gateway
    cache_key = gateway._build_cache_key(resolved)
    entry = gateway._clients[cache_key]
    entry.last_used -= 1.0

    await service.call_agent(resolved=resolved, query="second")

    assert DummyClient.instances == 2
    assert close_calls == ["https://example.com"]


@pytest.mark.asyncio
async def test_a2a_card_resolver_handles_full_card_url():
    async with httpx.AsyncClient() as httpx_client:
        client = A2AClient("http://example.com/.well-known/agent-card.json")
        resolver = client._build_card_resolver(httpx_client)

    assert resolver.base_url == "http://example.com"
    assert resolver.agent_card_path.lstrip("/") == AGENT_CARD_WELL_KNOWN_PATH.lstrip(
        "/"
    )


@pytest.mark.asyncio
async def test_a2a_card_resolver_handles_nested_card_url():
    async with httpx.AsyncClient() as httpx_client:
        client = A2AClient("http://example.com/a2a/.well-known/agent-card.json")
        resolver = client._build_card_resolver(httpx_client)

    assert resolver.base_url == "http://example.com/a2a"
    assert resolver.agent_card_path.lstrip("/") == AGENT_CARD_WELL_KNOWN_PATH.lstrip(
        "/"
    )


@pytest.mark.asyncio
async def test_a2a_client_supports_http_json_transport(monkeypatch):
    captured = {}

    class DummyClient:
        async def close(self):
            return None

    class DummyFactory:
        def __init__(self, config, consumers=None):
            captured["supported"] = config.supported_transports

        def create(self, _card, consumers=None, interceptors=None):
            return DummyClient()

    async def fake_get_agent_card(self):
        return SimpleNamespace(
            preferred_transport="HTTP+JSON",
            additional_interfaces=None,
            url="https://example.com",
        )

    monkeypatch.setattr(
        "app.integrations.a2a_client.client.ClientFactory", DummyFactory
    )
    monkeypatch.setattr(A2AClient, "get_agent_card", fake_get_agent_card)

    client = A2AClient("https://example.com")
    await client._get_client(streaming=False)
    await client.close()

    assert TransportProtocol.http_json in captured["supported"]
    assert TransportProtocol.jsonrpc in captured["supported"]


@pytest.mark.asyncio
async def test_a2a_client_builds_message_with_context_fields():
    client = A2AClient("https://example.com")
    message = client._build_message(
        "hello",
        context_id="ctx_123",
        metadata={"source": "test"},
    )

    assert len(message.parts) == 1
    part = message.parts[0]
    text_part = part if isinstance(part, TextPart) else getattr(part, "root", None)
    assert isinstance(text_part, TextPart)
    assert text_part.text == "hello"
    assert message.context_id == "ctx_123"
    assert message.metadata == {"source": "test"}


@pytest.mark.asyncio
async def test_a2a_client_generates_context_id_when_missing():
    client = A2AClient("https://example.com")

    message = client._build_message("hello", context_id=None)
    assert message.context_id
    UUID(message.context_id)

    message_blank = client._build_message("hello", context_id="  ")
    assert message_blank.context_id
    UUID(message_blank.context_id)


@pytest.mark.asyncio
async def test_a2a_gateway_fetches_card_detail(monkeypatch):
    settings = A2ASettings(
        enabled=True,
        default_timeout=5.0,
        max_connections=2,
        use_client_preference=False,
        agents={
            "demo": A2AAgentConfig(
                url="https://example.com",
                name="demo",
            )
        },
    )

    card = AgentCard(
        name="Demo",
        description="Demo agent",
        url="https://example.com",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        skills=[
            AgentSkill(
                id="skill-1",
                name="demo",
                description="demo",
                tags=["test"],
            )
        ],
    )

    class DummyClient:
        async def get_agent_card(self):
            return card

        async def close(self):
            return None

    gateway = A2AGateway(settings)

    async def _fake_get_client(_resolved):
        return DummyClient()

    monkeypatch.setattr(gateway, "_get_client", _fake_get_client)

    resolved = ResolvedAgent(
        name="demo",
        url="https://example.com",
        description=None,
        metadata={},
        headers={},
    )

    result = await gateway.fetch_agent_card_detail(
        resolved=resolved, raise_on_failure=True
    )
    assert result == card
