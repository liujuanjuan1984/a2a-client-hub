from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.features.invoke.extension_negotiation import (
    resolve_core_invoke_requested_extensions,
)
from app.integrations.a2a_extensions.capability_snapshot import (
    InvokeMetadataCapabilitySnapshot,
    ModelSelectionCapabilitySnapshot,
    RequestExecutionOptionsCapabilitySnapshot,
    StreamHintsCapabilitySnapshot,
)
from app.integrations.a2a_extensions.shared_contract import (
    INVOKE_METADATA_URI,
    MODEL_SELECTION_URI,
    SHARED_MODEL_FIELD,
    SHARED_SESSION_BINDING_URI,
    SHARED_SESSION_ID_FIELD,
)
from app.integrations.a2a_extensions.types import (
    ResolvedInvokeMetadataExtension,
    ResolvedInvokeMetadataField,
    ResolvedModelSelectionExtension,
    ResolvedSessionBindingExtension,
)
from tests.extensions.a2a_extensions_service_support import (
    _binding_snapshot,
    _capability_snapshot,
    _resolved_extension,
    _session_query_snapshot,
    _stream_hints_extension_fixture,
    _wire_contract_snapshot,
)


@pytest.mark.asyncio
async def test_resolve_core_invoke_requested_extensions_collects_relevant_uris():
    session_query_ext = _resolved_extension()
    snapshot = _capability_snapshot(
        session_query=_session_query_snapshot(session_query_ext),
        session_binding=_binding_snapshot(
            ext=ResolvedSessionBindingExtension(
                uri=SHARED_SESSION_BINDING_URI,
                required=False,
                provider_key="example_provider",
                metadata_field=SHARED_SESSION_ID_FIELD,
                behavior="request_scoped_session_routing",
                supported_metadata=("shared.session.provider", "shared.session.id"),
                provider_private_fields=(),
                shared_workspace_across_consumers=True,
                tenant_isolation="provider_managed",
            )
        ),
        invoke_metadata=InvokeMetadataCapabilitySnapshot(
            status="supported",
            ext=ResolvedInvokeMetadataExtension(
                uri=INVOKE_METADATA_URI,
                required=False,
                provider_key="example_provider",
                metadata_field="metadata.shared.invoke",
                behavior="merge_bound_metadata_into_invoke",
                applies_to_methods=("message/send", "message/stream"),
                fields=(
                    ResolvedInvokeMetadataField(
                        name="project_id",
                        required=True,
                    ),
                ),
                supported_metadata=("shared.invoke.bindings.project_id",),
            ),
        ),
        model_selection=ModelSelectionCapabilitySnapshot(
            status="supported",
            ext=ResolvedModelSelectionExtension(
                uri=MODEL_SELECTION_URI,
                required=False,
                provider_key="example_provider",
                metadata_field=SHARED_MODEL_FIELD,
                behavior="request_scoped_override",
                applies_to_methods=("message/send", "message/stream"),
                supported_metadata=(
                    "shared.model.providerID",
                    "shared.model.modelID",
                ),
                provider_private_fields=(),
            ),
        ),
        request_execution_options=RequestExecutionOptionsCapabilitySnapshot(
            status="supported",
            declared=True,
            consumed_by_hub=True,
            metadata_field="metadata.codex.execution",
            source_extensions=(session_query_ext.uri,),
        ),
        stream_hints=StreamHintsCapabilitySnapshot(
            status="supported",
            ext=_stream_hints_extension_fixture(),
        ),
        wire_contract=_wire_contract_snapshot(),
    )

    async def _resolve_capability_snapshot(*, runtime):
        assert runtime is not None
        return snapshot

    requested = await resolve_core_invoke_requested_extensions(
        runtime=SimpleNamespace(
            resolved=SimpleNamespace(url="https://example.com/a2a")
        ),
        metadata={
            "project_id": "proj-1",
            "shared": {
                "session": {"provider": "opencode", "id": "ses-1"},
                "invoke": {"bindings": {"project_id": "proj-1"}},
                "model": {"providerID": "openai", "modelID": "gpt-5"},
            },
            "codex": {"execution": {"approvalPolicy": "never"}},
        },
        require_stream_hints=True,
        extensions_service_getter=lambda: SimpleNamespace(
            resolve_capability_snapshot=_resolve_capability_snapshot
        ),
    )

    assert requested == (
        "urn:a2a:session-binding/v1",
        "urn:a2a:invoke-metadata/v1",
        "urn:opencode-a2a:extension:shared:model-selection:v1",
        "urn:opencode-a2a:extension:private:session-management:v1",
        "urn:a2a:stream-hints/v1",
    )


@pytest.mark.asyncio
async def test_resolve_core_invoke_requested_extensions_tolerates_snapshot_failure(
    caplog: pytest.LogCaptureFixture,
):
    async def _explode(*, runtime):
        assert runtime is not None
        raise RuntimeError("boom")

    runtime = SimpleNamespace(resolved=SimpleNamespace(url="https://example.com/a2a"))
    with caplog.at_level(logging.WARNING):
        requested = await resolve_core_invoke_requested_extensions(
            runtime=runtime,
            metadata={},
            require_stream_hints=True,
            extensions_service_getter=lambda: SimpleNamespace(
                resolve_capability_snapshot=_explode
            ),
        )

    assert requested == ()
    assert (
        "Failed to resolve capability snapshot for core invoke negotiation"
        in caplog.text
    )
