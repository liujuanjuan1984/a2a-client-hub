from __future__ import annotations

from app.schemas.a2a_extension import (
    A2AExtensionPermissionReplyRequest,
    A2AExtensionSessionCommandRequest,
)


def test_permission_reply_request_maps_working_directory_to_legacy_metadata() -> None:
    payload = A2AExtensionPermissionReplyRequest.model_validate(
        {
            "request_id": "perm-1",
            "reply": "once",
            "workingDirectory": "  /workspace/demo  ",
            "metadata": {"provider": "opencode"},
        }
    )

    assert payload.working_directory is None
    assert payload.metadata == {
        "provider": "opencode",
        "opencode": {"directory": "/workspace/demo"},
    }


def test_session_command_request_removes_empty_working_directory() -> None:
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

    assert payload.working_directory is None
    assert payload.metadata == {
        "opencode": {
            "project": "alpha",
        }
    }
