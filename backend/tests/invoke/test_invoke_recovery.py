from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.invoke.recovery import (
    build_rebound_invoke_payload,
    finalize_outbound_invoke_payload,
    resolve_session_binding_outbound_mode,
)
from app.integrations.a2a_extensions.errors import A2AExtensionUpstreamError
from app.schemas.a2a_invoke import A2AAgentInvokeRequest


def _fake_logger() -> SimpleNamespace:
    return SimpleNamespace(info=lambda *args, **kwargs: None)


def _capture_warning(
    sink: list[tuple[str, dict[str, object]]],
):
    def _warn(
        *,
        logger,  # noqa: ANN001, ARG001
        message: str,
        log_extra: dict[str, object],
        extra: dict[str, object] | None = None,
    ) -> None:
        sink.append((message, {**log_extra, **(extra or {})}))

    return _warn


async def _return_false(**kwargs) -> bool:  # noqa: ANN003, ARG001
    return False


def test_build_rebound_invoke_payload_applies_continue_binding_fields() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "locale": "zh-CN",
                "provider": "legacy",
                "externalSessionId": "legacy-sid",
            },
        }
    )

    rebound = build_rebound_invoke_payload(
        payload=payload,
        continue_payload={
            "conversationId": "conv-next",
            "metadata": {
                "provider": "OpenCode",
                "externalSessionId": "ses-upstream-1",
                "contextId": "ctx-next",
            },
        },
    )

    assert rebound.conversation_id == "conv-next"
    assert rebound.session_binding is not None
    assert rebound.session_binding.provider == "opencode"
    assert rebound.session_binding.external_session_id == "ses-upstream-1"
    assert rebound.metadata == {"locale": "zh-CN"}


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_applies_declared_contract() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "locale": "zh-CN",
                "provider": "legacy",
                "externalSessionId": "legacy-sid",
                "shared": {
                    "session": {
                        "id": "legacy-sid",
                        "provider": "legacy",
                    },
                    "model": {
                        "providerID": "openai",
                        "modelID": "gpt-5",
                    },
                },
            },
            "sessionBinding": {
                "provider": "OpenCode",
                "externalSessionId": "ses-upstream-1",
            },
        }
    )

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={},
        resolve_outbound_mode=_return_false,
    )

    assert finalized.metadata == {
        "locale": "zh-CN",
        "shared": {
            "model": {
                "providerID": "openai",
                "modelID": "gpt-5",
            },
            "session": {
                "id": "ses-upstream-1",
                "provider": "opencode",
            },
        },
    }
    assert finalized.session_binding is None


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_discards_incomplete_binding_and_warns() -> (
    None
):
    warnings: list[tuple[str, dict[str, object]]] = []
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {"locale": "zh-CN"},
            "sessionBinding": {"provider": "OpenCode"},
        }
    )

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={"agent_id": "agent-1"},
        resolve_outbound_mode=_return_false,
        log_warning_fn=_capture_warning(warnings),
    )

    assert finalized.metadata == {"locale": "zh-CN"}
    assert finalized.session_binding is None
    assert warnings == [
        (
            "Discarding incomplete session binding intent without external session id",
            {
                "agent_id": "agent-1",
                "session_binding_discarded": True,
                "session_binding_discard_reason": "missing_external_session_id",
                "session_binding_provider": "opencode",
                "session_binding_source": "session_binding_intent",
            },
        )
    ]


@pytest.mark.asyncio
async def test_resolve_session_binding_outbound_mode_warns_on_upstream_failure() -> (
    None
):
    warnings: list[tuple[str, dict[str, object]]] = []

    class _FailingExtensionsService:
        async def resolve_session_binding(self, *, runtime):  # noqa: ARG002
            raise A2AExtensionUpstreamError(
                message="card fetch failed",
                error_code="upstream_unavailable",
            )

    include_legacy_root = await resolve_session_binding_outbound_mode(
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={"agent_id": "agent-1"},
        extensions_service_getter=lambda: _FailingExtensionsService(),
        log_warning_fn=_capture_warning(warnings),
    )

    assert include_legacy_root is True
    assert warnings == [
        (
            "Session binding capability resolution failed upstream; using compatibility fallback",
            {
                "agent_id": "agent-1",
                "session_binding_resolution_error": "upstream_fetch_failed",
                "session_binding_resolution_detail": "card fetch failed",
                "session_binding_fallback_used": True,
            },
        )
    ]
