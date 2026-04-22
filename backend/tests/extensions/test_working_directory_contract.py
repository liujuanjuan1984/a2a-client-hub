from __future__ import annotations

from app.features.invoke.route_runner import _adapt_invoke_metadata_for_upstream
from app.features.working_directory import (
    adapt_working_directory_metadata_for_upstream,
)
from app.schemas.a2a_extension import (
    A2AExtensionPermissionReplyRequest,
    A2AExtensionSessionCommandRequest,
    A2AModelDiscoveryRequest,
)
from app.schemas.a2a_invoke import A2AAgentInvokeRequest


def test_permission_reply_request_keeps_working_directory_stable() -> None:
    payload = A2AExtensionPermissionReplyRequest.model_validate(
        {
            "request_id": "perm-1",
            "reply": "once",
            "workingDirectory": "  /workspace/demo  ",
            "metadata": {"provider": "opencode"},
        }
    )

    assert payload.working_directory == "  /workspace/demo  "
    assert payload.metadata == {"provider": "opencode"}


def test_session_command_request_keeps_empty_working_directory_stable() -> None:
    payload = A2AExtensionSessionCommandRequest.model_validate(
        {
            "request": {"command": "/review", "arguments": ""},
            "workingDirectory": "   ",
            "metadata": {
                "opencode": {
                    "directory": "/workspace/demo",
                    "project": "alpha",
                }
            },
        }
    )

    assert payload.working_directory == "   "
    assert payload.metadata == {
        "opencode": {
            "directory": "/workspace/demo",
            "project": "alpha",
        }
    }


def test_model_discovery_request_keeps_working_directory_stable() -> None:
    payload = A2AModelDiscoveryRequest.model_validate(
        {
            "provider_id": "openai",
            "workingDirectory": "  /workspace/demo  ",
        }
    )

    assert payload.working_directory == "  /workspace/demo  "
    assert payload.session_metadata is None


def test_provider_adapter_maps_stable_working_directory_to_provider_metadata() -> None:
    metadata = adapt_working_directory_metadata_for_upstream(
        {"workingDirectory": "/workspace/demo", "locale": "en-CA"},
        None,
        metadata_namespace="opencode",
    )

    assert metadata == {
        "locale": "en-CA",
        "opencode": {"directory": "/workspace/demo"},
    }


def test_provider_adapter_removes_provider_directory_for_empty_stable_override() -> (
    None
):
    metadata = adapt_working_directory_metadata_for_upstream(
        {"opencode": {"directory": "/workspace/demo", "project": "alpha"}},
        "   ",
        metadata_namespace="opencode",
    )

    assert metadata == {"opencode": {"project": "alpha"}}


def test_provider_adapter_does_not_read_legacy_provider_directory() -> None:
    metadata = adapt_working_directory_metadata_for_upstream(
        {"opencode": {"directory": "/workspace/demo", "project": "alpha"}},
        None,
        metadata_namespace="opencode",
    )

    assert metadata == {"opencode": {"project": "alpha"}}


def test_extension_adapter_returns_none_for_empty_metadata() -> None:
    metadata = adapt_working_directory_metadata_for_upstream(
        None,
        None,
        metadata_namespace="opencode",
        empty_as_none=True,
    )

    assert metadata is None


def test_invoke_upstream_adapter_uses_bound_provider_namespace() -> None:
    payload = A2AAgentInvokeRequest(
        query="Continue",
        metadata={
            "shared": {
                "session": {
                    "provider": "codex",
                    "id": "ses-1",
                }
            }
        },
        workingDirectory="/workspace/demo",
    )

    metadata = _adapt_invoke_metadata_for_upstream(payload)

    assert metadata == {
        "shared": {
            "session": {
                "provider": "codex",
                "id": "ses-1",
            }
        },
        "codex": {"directory": "/workspace/demo"},
    }
