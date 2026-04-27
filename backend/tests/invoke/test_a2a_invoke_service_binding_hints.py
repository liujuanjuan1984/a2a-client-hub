from __future__ import annotations

from tests.invoke.a2a_invoke_service_support import (
    a2a_invoke_service,
)


def _session_metadata(
    *,
    provider: str | None = None,
    session_id: str | None = None,
    context_id: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if context_id is not None:
        metadata["contextId"] = context_id
    if provider is not None or session_id is not None:
        session: dict[str, str] = {}
        if session_id is not None:
            session["id"] = session_id
        if provider is not None:
            session["provider"] = provider
        metadata["shared"] = {"session": session}
    return metadata


def test_extract_binding_hints_from_serialized_event():
    (
        context_id,
        metadata,
    ) = a2a_invoke_service.extract_binding_hints_from_serialized_event(
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_AGENT",
                "parts": [{"text": "ok"}],
                "contextId": "ctx-1",
                "metadata": {
                    "shared": {
                        "session": {
                            "id": "upstream-1",
                            "provider": "OpenCode",
                        }
                    },
                },
            }
        }
    )
    assert context_id == "ctx-1"
    assert metadata == _session_metadata(
        provider="opencode",
        session_id="upstream-1",
    )


def test_extract_binding_hints_from_invoke_result_merges_raw_payload():
    class _RawPayload:
        def model_dump(self, **kwargs):
            return {
                "message": {
                    "messageId": "msg-raw",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "ok"}],
                    "contextId": "ctx-from-raw",
                    "metadata": {
                        "shared": {
                            "session": {
                                "id": "raw-upstream",
                                "provider": "opencode",
                            }
                        },
                    },
                }
            }

    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "message": {
                "messageId": "msg-result",
                "role": "ROLE_AGENT",
                "parts": [{"text": "ok"}],
                "contextId": "ctx-from-result",
                "metadata": {
                    "shared": {
                        "session": {
                            "id": "result-upstream",
                        }
                    }
                },
            },
            "raw": _RawPayload(),
        }
    )
    assert context_id == "ctx-from-raw"
    assert metadata == _session_metadata(
        provider="opencode",
        session_id="raw-upstream",
    )


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
    assert metadata == {}


def test_extract_binding_hints_ignores_legacy_root_session_metadata():
    context_id, metadata = (
        a2a_invoke_service.extract_binding_hints_from_serialized_event(
            {
                "message": {
                    "messageId": "msg-legacy",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "ok"}],
                    "contextId": "ctx-legacy",
                    "metadata": {
                        "provider": "OpenCode",
                        "externalSessionId": "legacy-upstream-1",
                    },
                }
            }
        )
    )
    assert context_id == "ctx-legacy"
    assert metadata == {}


def test_extract_binding_hints_extracts_canonical_shared_session_id():
    context_id, metadata = a2a_invoke_service.extract_binding_hints_from_invoke_result(
        {
            "success": True,
            "content": "ok",
            "message": {
                "messageId": "msg-canonical",
                "role": "ROLE_AGENT",
                "parts": [{"text": "ok"}],
                "metadata": {
                    "shared": {
                        "session": {
                            "id": "nested-upstream-session",
                            "provider": "OpenCode",
                        }
                    },
                },
            },
        }
    )
    assert context_id is None
    assert metadata == _session_metadata(
        provider="opencode",
        session_id="nested-upstream-session",
    )


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
    assert metadata == {}


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
    assert metadata == {}


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
