from __future__ import annotations

from tests.invoke.a2a_invoke_service_support import (
    a2a_invoke_service,
)


def test_extract_binding_hints_from_serialized_event():
    (
        context_id,
        metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
        {
            "contextId": "ctx-1",
            "metadata": {
                "provider": "OpenCode",
                "shared": {
                    "session": {
                        "id": "upstream-1",
                    }
                },
            },
        }
    )
    assert context_id == "ctx-1"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "upstream-1"


def test_extract_binding_hints_from_invoke_result_merges_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):
            return {
                "contextId": "ctx-from-raw",
                "metadata": {
                    "provider": "opencode",
                    "shared": {
                        "session": {
                            "id": "raw-upstream",
                        }
                    },
                },
            }

    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "contextId": "ctx-from-result",
            "metadata": {"externalSessionId": "result-upstream"},
            "raw": _RawPayload(),
        }
    )
    assert context_id == "ctx-from-raw"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "raw-upstream"


def test_extract_binding_hints_ignores_session_id_aliases():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "result": {
                "provider": "OpenCode",
                "session_id": "alias-upstream-session",
            },
        }
    )
    assert context_id is None
    assert metadata["provider"] == "opencode"


def test_extract_binding_hints_falls_back_to_legacy_root_session_metadata():
    context_id, metadata = (
        a2a_invoke_service.extract_binding_hints_from_serialized_event(
            {
                "contextId": "ctx-legacy",
                "metadata": {
                    "provider": "OpenCode",
                    "externalSessionId": "legacy-upstream-1",
                },
            }
        )
    )
    assert context_id == "ctx-legacy"
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "legacy-upstream-1"


def test_extract_binding_hints_extracts_canonical_shared_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "provider": "OpenCode",
                "shared": {
                    "session": {
                        "id": "nested-upstream-session",
                    }
                },
            },
        }
    )
    assert context_id is None
    assert metadata["provider"] == "opencode"
    assert metadata["externalSessionId"] == "nested-upstream-session"


def test_extract_binding_hints_ignores_legacy_flat_opencode_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "opencode_session_id": "legacy-flat-session-id",
            },
        }
    )
    assert context_id is None
    assert "provider" not in metadata
    assert "externalSessionId" not in metadata


def test_extract_binding_hints_ignores_legacy_flat_external_session_id_aliases():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "metadata": {
                "external_session_id": "legacy-flat-session-id",
                "upstream_session_id": "legacy-upstream-session-id",
            },
        }
    )
    assert context_id is None
    assert "provider" not in metadata
    assert "externalSessionId" not in metadata


def test_extract_readable_content_prefers_raw_history_agent_message():
    readable = a2a_invoke_service.extract_readable_content_from_invoke_result(
        {
            "success": True,
            "content": '{"content":"opaque"}',
            "raw": {
                "history": [
                    {"role": "user", "parts": [{"kind": "text", "text": "Hi"}]},
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "Hello from agent"}],
                    },
                ]
            },
        }
    )
    assert readable == "Hello from agent"


def test_extract_readable_content_parses_json_string_content():
    readable = a2a_invoke_service.extract_readable_content_from_invoke_result(
        {
            "success": True,
            "content": (
                '{"history":[{"role":"user","parts":[{"text":"Q"}]},'
                '{"role":"assistant","parts":[{"text":"A"}]}]}'
            ),
        }
    )
    assert readable == "A"
