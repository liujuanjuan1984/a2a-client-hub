import pytest

from app.core.config import settings
from app.features.agents.common.card_validation import fetch_and_validate_agent_card
from app.features.invoke.service_streaming import A2AInvokeStreamingRuntime
from tests.support.a2a import (
    build_agent_card_payload,
    build_session_query_extension_payload,
    parse_agent_card,
)


class _DummyCard:
    def model_dump(self, **kwargs):
        return {"name": "dummy"}


class _DummyGateway:
    async def fetch_agent_card_detail(self, **kwargs):
        return _DummyCard()


def _build_extension_card_payload(
    *, extensions: list[dict[str, object]]
) -> dict[str, object]:
    payload = build_agent_card_payload(extensions=extensions)
    payload["name"] = "dummy"
    payload["description"] = "dummy"
    return payload


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_validation_errors_gated(monkeypatch):
    monkeypatch.setattr(
        "app.features.agents.common.card_validation.validate_agent_card_payload",
        lambda payload: type(
            "_ValidationResult",
            (),
            {"errors": ["bad-card"], "warnings": []},
        )(),
    )

    monkeypatch.setattr(settings, "debug", False)
    resp = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )
    assert resp.validation_errors is None

    monkeypatch.setattr(settings, "debug", True)
    resp_debug = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )
    assert resp_debug.validation_errors == ["bad-card"]


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_exposes_warning_only_success(monkeypatch):
    monkeypatch.setattr(
        "app.features.agents.common.card_validation.validate_agent_card_payload",
        lambda payload: type(
            "_ValidationResult",
            (),
            {
                "errors": [],
                "warnings": ["Field 'skills' array is empty."],
            },
        )(),
    )

    monkeypatch.setattr(settings, "debug", False)
    resp = await fetch_and_validate_agent_card(
        gateway=_DummyGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.message == "Agent card validated with warnings"
    assert resp.validation_errors is None
    assert resp.validation_warnings == ["Field 'skills' array is empty."]


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_exposes_invalid_session_query_contract() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            return _build_extension_card_payload(
                extensions=[
                    build_session_query_extension_payload(
                        uri="urn:opencode-a2a:session-query/v1",
                        pagination={
                            "mode": "page_size",
                            "default_size": 20,
                        },
                    ),
                    {
                        "uri": "urn:a2a:compatibility-profile/v1",
                        "params": {
                            "extension_retention": {},
                            "method_retention": {},
                            "service_behaviors": {
                                "classification": "stable-service-semantics",
                                "methods": {"tasks/cancel": {"retention": "stable"}},
                            },
                            "consumer_guidance": ["Treat query methods as stable."],
                        },
                    },
                ]
            )

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            return parse_agent_card(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.shared_session_query is not None
    assert resp.shared_session_query.status == "invalid"
    assert resp.message == "Agent card validated with warnings"
    assert resp.validation_warnings == [
        (
            "Shared session query contract is invalid: Extension contract "
            "missing/invalid 'pagination.max_size' for mode 'page_size'"
        )
    ]


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_accepts_limit_and_optional_cursor_mode() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            return _build_extension_card_payload(
                extensions=[
                    build_session_query_extension_payload(
                        uri="urn:opencode-a2a:session-query/v1",
                        methods={
                            "list_sessions": "opencode.sessions.list",
                            "get_session_messages": ("opencode.sessions.messages.list"),
                        },
                        pagination={
                            "mode": "limit_and_optional_cursor",
                            "default_limit": 20,
                            "max_limit": 100,
                            "params": ["limit", "before"],
                            "cursor_param": "before",
                            "result_cursor_field": "next_cursor",
                            "cursor_applies_to": ["opencode.sessions.messages.list"],
                        },
                        result_envelope={
                            "raw": True,
                            "items": True,
                            "pagination": True,
                        },
                    )
                ]
            )

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            return parse_agent_card(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.shared_session_query is not None
    assert resp.shared_session_query.status == "supported"
    assert resp.shared_session_query.declared_contract_family == "opencode"
    assert resp.shared_session_query.pagination_mode == "limit_and_optional_cursor"
    assert resp.extension_capabilities is not None
    assert resp.extension_capabilities.session_control.command.declared is False
    assert resp.message == "Agent card validated"


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_accepts_codex_session_query_contract() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            return _build_extension_card_payload(
                extensions=[
                    build_session_query_extension_payload(
                        uri="urn:codex-a2a:codex-session-query/v1",
                        provider="codex",
                        methods={
                            "list_sessions": "codex.sessions.list",
                            "get_session_messages": "codex.sessions.messages.list",
                            "prompt_async": "codex.sessions.prompt_async",
                            "command": "codex.sessions.command",
                        },
                        pagination={
                            "mode": "limit",
                            "default_limit": 20,
                            "max_limit": 100,
                        },
                        method_contracts={
                            "codex.sessions.prompt_async": {
                                "params": {"required": ["session_id", "request.parts"]}
                            },
                            "codex.sessions.command": {
                                "params": {
                                    "required": [
                                        "session_id",
                                        "request.command",
                                    ],
                                    "optional": ["request.arguments"],
                                }
                            },
                        },
                        result_envelope={},
                    ),
                    {
                        "uri": "urn:a2a:compatibility-profile/v1",
                        "params": {
                            "extension_retention": {},
                            "method_retention": {},
                            "service_behaviors": {
                                "classification": "stable-service-semantics",
                                "methods": {"tasks/cancel": {"retention": "stable"}},
                            },
                            "consumer_guidance": [
                                "Treat codex session query methods as stable."
                            ],
                        },
                    },
                ]
            )

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            return parse_agent_card(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.shared_session_query is not None
    assert resp.shared_session_query.status == "supported"
    assert resp.shared_session_query.declared_contract_family == "codex"
    assert resp.shared_session_query.pagination_mode == "limit"
    assert resp.extension_capabilities is not None
    assert resp.extension_capabilities.session_control.prompt_async.declared is True
    assert resp.message == "Agent card validated"


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_exposes_extension_capabilities_summary() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            payload = _build_extension_card_payload(
                extensions=[
                    build_session_query_extension_payload(
                        uri="urn:opencode-a2a:session-query/v1",
                        methods={
                            "list_sessions": "opencode.sessions.list",
                            "get_session_messages": "opencode.sessions.messages.list",
                        },
                        pagination={
                            "mode": "limit",
                            "default_limit": 20,
                            "max_limit": 100,
                        },
                        result_envelope={
                            "raw": True,
                            "items": True,
                            "pagination": True,
                        },
                    )
                ]
            )
            payload["capabilities"]["extensions"][0]["params"][
                "request_execution_options"
            ] = {
                "metadata_field": "metadata.codex.execution",
                "fields": ["model", "effort"],
                "persists_for_thread": True,
                "notes": ["Execution overrides are provider-private."],
            }
            return payload

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            return parse_agent_card(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.extension_capabilities is not None
    assert resp.extension_capabilities.request_execution_options.status == "supported"
    assert resp.extension_capabilities.request_execution_options.consumed_by_hub is True
    assert resp.extension_capabilities.request_execution_options.source_extensions == [
        "urn:opencode-a2a:session-query/v1"
    ]


@pytest.mark.asyncio
async def test_fetch_and_validate_agent_card_exposes_invalid_compatibility_profile() -> (
    None
):
    class _ExtensionCard:
        def model_dump(self, **kwargs):
            return {
                "name": "dummy",
                "description": "dummy",
                "version": "1.0",
                "supportedInterfaces": [
                    {
                        "url": "https://example.com/jsonrpc",
                        "protocolBinding": "JSONRPC",
                    }
                ],
                "capabilities": {
                    "extensions": [
                        {
                            "uri": "urn:a2a:compatibility-profile/v1",
                            "params": {
                                "extension_retention": {
                                    "urn:opencode-a2a:session-query/v1": {
                                        "surface": "jsonrpc-extension",
                                        "availability": "always",
                                        "retention": "stable",
                                    }
                                },
                                "method_retention": [],
                                "service_behaviors": {
                                    "classification": "stable-service-semantics"
                                },
                                "consumer_guidance": [
                                    "Treat opencode.sessions.* as provider-private."
                                ],
                            },
                        }
                    ]
                },
                "defaultInputModes": [],
                "defaultOutputModes": [],
                "skills": [{"id": "s1", "name": "s1", "description": "d", "tags": []}],
            }

    class _ExtensionGateway:
        async def fetch_agent_card_detail(self, **kwargs):
            return parse_agent_card(_ExtensionCard().model_dump())

    resp = await fetch_and_validate_agent_card(
        gateway=_ExtensionGateway(), resolved=object()
    )

    assert resp.success is True
    assert resp.compatibility_profile is not None
    assert resp.compatibility_profile.status == "invalid"
    assert resp.message == "Agent card validated with warnings"
    assert resp.validation_warnings == [
        "Compatibility profile advisory is invalid and will be ignored: "
        "Extension contract missing/invalid 'params.method_retention'"
    ]


def test_serialize_stream_event_validation_errors_gated(monkeypatch):
    class _DummyEvent:
        def model_dump(self, **kwargs):
            return {"content": "ok"}

    validate_message = lambda payload: ["bad-event"]  # noqa: E731

    monkeypatch.setattr(settings, "debug", False)
    payload = A2AInvokeStreamingRuntime.serialize_stream_event(
        _DummyEvent(), validate_message=validate_message
    )
    assert "validation_errors" not in payload

    monkeypatch.setattr(settings, "debug", True)
    payload_debug = A2AInvokeStreamingRuntime.serialize_stream_event(
        _DummyEvent(), validate_message=validate_message
    )
    assert payload_debug["validation_errors"] == ["bad-event"]
