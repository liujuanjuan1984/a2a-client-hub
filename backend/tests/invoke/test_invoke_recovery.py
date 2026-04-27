from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.features.invoke.recovery import (
    InvokeMetadataBindingRequiredError,
    build_rebound_invoke_payload,
    finalize_outbound_invoke_payload,
    resolve_session_binding_outbound_mode,
    validate_provider_aware_continue_session,
)
from app.integrations.a2a_extensions.errors import (
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.integrations.a2a_extensions.service_common import ExtensionCallResult
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedInvokeMetadataField,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest


def _fake_logger() -> SimpleNamespace:
    return SimpleNamespace(info=lambda *args, **kwargs: None)


def _capture_warning(
    sink: list[tuple[str, dict[str, object]]],
):
    def _warn(
        *,
        logger,
        message: str,
        log_extra: dict[str, object],
        extra: dict[str, object] | None = None,
    ) -> None:
        sink.append((message, {**log_extra, **(extra or {})}))

    return _warn


def _session_metadata(
    *,
    provider: str | None = None,
    session_id: str | None = None,
    context_id: str | None = None,
    **extra: object,
) -> dict[str, object]:
    metadata: dict[str, object] = dict(extra)
    if context_id is not None:
        metadata["contextId"] = context_id
    if provider is not None or session_id is not None:
        session: dict[str, str] = {}
        if session_id is not None:
            session["id"] = session_id
        if provider is not None:
            session["provider"] = provider
        metadata["shared"] = {
            **(
                metadata.get("shared")
                if isinstance(metadata.get("shared"), dict)
                else {}
            ),
            "session": session,
        }
    return metadata


def _invoke_metadata_extension() -> ResolvedInvokeMetadataExtension:
    return ResolvedInvokeMetadataExtension(
        uri="urn:a2a:invoke-metadata/v1",
        required=False,
        provider="commonground",
        metadata_field="metadata.shared.invoke",
        behavior="merge_bound_metadata_into_invoke",
        applies_to_methods=("message/send", "message/stream"),
        fields=(
            ResolvedInvokeMetadataField(name="project_id", required=True),
            ResolvedInvokeMetadataField(name="channel_id", required=True),
        ),
        supported_metadata=(
            "shared.invoke.bindings.project_id",
            "shared.invoke.bindings.channel_id",
        ),
    )


def test_build_rebound_invoke_payload_applies_continue_binding_fields() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": _session_metadata(
                provider="legacy",
                session_id="legacy-sid",
                locale="zh-CN",
            ),
        }
    )

    rebound = build_rebound_invoke_payload(
        payload=payload,
        continue_payload={
            "conversationId": "conv-next",
            "metadata": _session_metadata(
                provider="OpenCode",
                session_id="ses-upstream-1",
                context_id="ctx-next",
            ),
        },
    )

    assert rebound.conversation_id == "conv-next"
    assert rebound.session_binding is not None
    assert rebound.session_binding.provider == "opencode"
    assert rebound.session_binding.external_session_id == "ses-upstream-1"
    assert rebound.metadata == {"locale": "zh-CN"}


@pytest.mark.asyncio
async def test_validate_provider_aware_continue_session_skips_without_session_id() -> (
    None
):
    result = await validate_provider_aware_continue_session(
        runtime=SimpleNamespace(),
        continue_payload={"metadata": _session_metadata(provider="opencode")},
        logger=_fake_logger(),
        log_extra={},
    )

    assert result == "skipped"


@pytest.mark.asyncio
async def test_validate_provider_aware_continue_session_validates_with_extension_response() -> (
    None
):
    observed: dict[str, object] = {}

    class _ExtensionsService:
        async def continue_session(self, *, runtime, session_id):
            observed["session_id"] = session_id
            return ExtensionCallResult(success=True, result={"ok": True})

    result = await validate_provider_aware_continue_session(
        runtime=SimpleNamespace(),
        continue_payload={
            "metadata": _session_metadata(
                provider="opencode",
                session_id="ses-upstream-1",
            )
        },
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
    )

    assert result == "validated"
    assert observed["session_id"] == "ses-upstream-1"


@pytest.mark.asyncio
async def test_validate_provider_aware_continue_session_returns_failed_for_explicit_upstream_failure() -> (
    None
):
    warnings: list[tuple[str, dict[str, object]]] = []

    class _ExtensionsService:
        async def continue_session(self, *, runtime, session_id):
            return ExtensionCallResult(
                success=False,
                error_code="session_not_found",
                source="upstream_a2a",
            )

    result = await validate_provider_aware_continue_session(
        runtime=SimpleNamespace(),
        continue_payload={
            "metadata": _session_metadata(
                provider="opencode",
                session_id="ses-upstream-1",
            )
        },
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
        log_warning_fn=_capture_warning(warnings),
    )

    assert result == "failed"
    assert warnings[0][1]["session_recovery_error_code"] == "session_not_found"


@pytest.mark.asyncio
async def test_validate_provider_aware_continue_session_skips_when_extension_is_unsupported() -> (
    None
):
    class _ExtensionsService:
        async def continue_session(self, *, runtime, session_id):
            raise A2AExtensionNotSupportedError("not supported")

    result = await validate_provider_aware_continue_session(
        runtime=SimpleNamespace(),
        continue_payload={
            "metadata": _session_metadata(
                provider="opencode",
                session_id="ses-upstream-1",
            )
        },
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
    )

    assert result == "skipped"


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_applies_declared_contract() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": _session_metadata(
                provider="legacy",
                session_id="legacy-sid",
                locale="zh-CN",
                shared={
                    "session": {
                        "id": "legacy-sid",
                        "provider": "legacy",
                    },
                    "model": {
                        "providerID": "openai",
                        "modelID": "gpt-5",
                    },
                },
            ),
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
async def test_finalize_outbound_invoke_payload_injects_bound_invoke_metadata() -> None:
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "locale": "zh-CN",
                "shared": {
                    "invoke": {
                        "bindings": {
                            "project_id": "proj-1",
                            "channel_id": "chan-1",
                        }
                    }
                },
            },
        }
    )

    class _ExtensionsService:
        async def resolve_invoke_metadata(self, *, runtime):
            return _invoke_metadata_extension()

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
    )

    assert finalized.metadata == {
        "locale": "zh-CN",
        "project_id": "proj-1",
        "channel_id": "chan-1",
    }


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_prefers_request_override_over_bound_metadata() -> (
    None
):
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "project_id": "request-project",
                "shared": {
                    "invoke": {
                        "bindings": {
                            "project_id": "bound-project",
                            "channel_id": "bound-channel",
                        }
                    }
                },
            },
        }
    )

    class _ExtensionsService:
        async def resolve_invoke_metadata(self, *, runtime):
            return _invoke_metadata_extension()

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
    )

    assert finalized.metadata == {
        "project_id": "request-project",
        "channel_id": "bound-channel",
    }


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_applies_agent_defaults_after_bindings() -> (
    None
):
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "shared": {
                    "invoke": {
                        "bindings": {
                            "project_id": "bound-project",
                        }
                    }
                },
            },
        }
    )

    class _ExtensionsService:
        async def resolve_invoke_metadata(self, *, runtime):
            return _invoke_metadata_extension()

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a"),
            invoke_metadata_defaults={
                "project_id": "default-project",
                "channel_id": "default-channel",
            },
        ),
        logger=_fake_logger(),
        log_extra={},
        extensions_service_getter=lambda: _ExtensionsService(),
    )

    assert finalized.metadata == {
        "project_id": "bound-project",
        "channel_id": "default-channel",
    }


@pytest.mark.asyncio
async def test_finalize_outbound_invoke_payload_raises_when_declared_fields_are_unbound() -> (
    None
):
    payload = A2AAgentInvokeRequest.model_validate(
        {
            "query": "hello",
            "conversationId": str(uuid4()),
            "metadata": {
                "shared": {
                    "invoke": {
                        "bindings": {
                            "project_id": "proj-1",
                        }
                    }
                },
            },
        }
    )

    class _ExtensionsService:
        async def resolve_invoke_metadata(self, *, runtime):
            return _invoke_metadata_extension()

    with pytest.raises(InvokeMetadataBindingRequiredError) as exc_info:
        await finalize_outbound_invoke_payload(
            payload=payload,
            runtime=SimpleNamespace(
                resolved=SimpleNamespace(
                    name="Demo Agent", url="https://example.com/a2a"
                )
            ),
            logger=_fake_logger(),
            log_extra={},
            extensions_service_getter=lambda: _ExtensionsService(),
        )

    assert exc_info.value.missing_params == ({"name": "channel_id", "required": True},)


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

    class _UnsupportedInvokeMetadataService:
        async def resolve_invoke_metadata(self, *, runtime):
            raise A2AExtensionNotSupportedError("Invoke metadata extension not found")

    finalized = await finalize_outbound_invoke_payload(
        payload=payload,
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(name="Demo Agent", url="https://example.com/a2a")
        ),
        logger=_fake_logger(),
        log_extra={"agent_id": "agent-1"},
        extensions_service_getter=lambda: _UnsupportedInvokeMetadataService(),
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
        async def resolve_session_binding(self, *, runtime):
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
