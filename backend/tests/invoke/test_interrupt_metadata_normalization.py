import json
from pathlib import Path

from app.features.invoke.stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
)
from app.features.sessions.common import (
    build_interrupt_block_view,
    build_interrupt_lifecycle_message_code,
    build_interrupt_lifecycle_message_content,
    deserialize_interrupt_event_block_content,
    normalize_interrupt_lifecycle_event,
    serialize_interrupt_event_block_content,
)

_MESSAGE_CASES = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "docs/contracts/interrupt-lifecycle-message-cases.json"
    ).read_text(encoding="utf-8")
)


def test_extract_interrupt_lifecycle_keeps_permission_display_message() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input-required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "perm-1",
                    "type": "permission",
                    "details": {
                        "permission": "approval",
                        "patterns": ["/repo/.env"],
                        "request": {
                            "description": "Agent wants to read the environment file."
                        },
                    },
                }
            }
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "perm-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "approval",
            "patterns": ["/repo/.env"],
            "display_message": "Agent wants to read the environment file.",
        },
    }


def test_extract_interrupt_lifecycle_keeps_question_descriptions() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input_required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "q-1",
                    "type": "question",
                    "details": {
                        "description": "Please confirm how the agent should continue.",
                        "questions": [
                            {
                                "title": "Approval",
                                "prompt": "Proceed with deployment?",
                                "description": "This will update the production service.",
                                "options": [{"label": "Yes", "value": "yes"}],
                            }
                        ],
                    },
                }
            }
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "q-1",
        "type": "question",
        "phase": "asked",
        "details": {
            "display_message": "Please confirm how the agent should continue.",
            "questions": [
                {
                    "header": "Approval",
                    "question": "Proceed with deployment?",
                    "description": "This will update the production service.",
                    "options": [
                        {
                            "label": "Yes",
                            "description": None,
                            "value": "yes",
                        }
                    ],
                }
            ],
        },
    }


def test_extract_interrupt_lifecycle_keeps_permissions_display_message() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input-required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "perms-1",
                    "type": "permissions",
                    "details": {
                        "display_message": "Approve the requested workspace access.",
                        "permissions": {
                            "fileSystem": {"write": ["/workspace/project"]}
                        },
                    },
                }
            }
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "perms-1",
        "type": "permissions",
        "phase": "asked",
        "details": {
            "display_message": "Approve the requested workspace access.",
            "permissions": {"fileSystem": {"write": ["/workspace/project"]}},
        },
    }


def test_extract_interrupt_lifecycle_keeps_elicitation_details() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input_required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "eli-1",
                    "type": "elicitation",
                    "details": {
                        "description": "Select the target folder.",
                        "mode": "form",
                        "server_name": "workspace-server",
                        "requested_schema": {
                            "type": "object",
                            "properties": {"folder": {"type": "string"}},
                        },
                        "url": "https://example.com/form",
                        "elicitation_id": "elicitation-1",
                        "meta": {"source": "upstream"},
                    },
                }
            }
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "eli-1",
        "type": "elicitation",
        "phase": "asked",
        "details": {
            "display_message": "Select the target folder.",
            "mode": "form",
            "server_name": "workspace-server",
            "requested_schema": {
                "type": "object",
                "properties": {"folder": {"type": "string"}},
            },
            "url": "https://example.com/form",
            "elicitation_id": "elicitation-1",
            "meta": {"source": "upstream"},
        },
    }


def test_extract_interrupt_lifecycle_treats_auth_required_as_asked() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "auth_required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "auth-1",
                    "type": "permission",
                    "details": {
                        "permission": "login",
                        "patterns": [],
                    },
                }
            }
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "auth-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "login",
            "patterns": [],
        },
    }


def test_extract_interrupt_lifecycle_ignores_codex_private_permission_details() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input-required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "perm-codex-1",
                    "type": "permission",
                    "details": {},
                }
            },
            "codex": {
                "interrupt": {
                    "metadata": {
                        "method": "execCommandApproval",
                        "raw": {
                            "request": {
                                "description": "Agent wants to read the environment file."
                            },
                            "parsedCmd": [
                                {
                                    "cmd": "cat .env",
                                    "path": "/repo/.env",
                                    "type": "read",
                                }
                            ],
                        },
                    }
                }
            },
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "perm-codex-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": None,
            "patterns": [],
        },
    }


def test_extract_interrupt_lifecycle_ignores_codex_private_question_details() -> None:
    payload = {
        "kind": "status-update",
        "status": {"state": "input_required"},
        "metadata": {
            "shared": {
                "interrupt": {
                    "request_id": "q-codex-1",
                    "type": "question",
                    "details": {"questions": []},
                }
            },
            "codex": {
                "interrupt": {
                    "metadata": {
                        "method": "item/tool/requestUserInput",
                        "raw": {
                            "context": {
                                "description": "Please confirm how the agent should continue."
                            },
                            "questions": [
                                {
                                    "header": "Deploy",
                                    "question": "Proceed with deployment?",
                                    "options": [{"label": "Yes", "value": "yes"}],
                                }
                            ],
                        },
                    }
                }
            },
        },
    }

    assert extract_interrupt_lifecycle_from_serialized_event(payload) == {
        "request_id": "q-codex-1",
        "type": "question",
        "phase": "asked",
        "details": {
            "questions": [],
        },
    }


def test_normalize_interrupt_lifecycle_event_keeps_legacy_nested_permission_text() -> (
    None
):
    event = {
        "request_id": "perm-legacy-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "approval",
            "context": {"message": "Agent requests approval to continue."},
        },
    }

    assert normalize_interrupt_lifecycle_event(event) == {
        "request_id": "perm-legacy-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "approval",
            "patterns": [],
            "display_message": "Agent requests approval to continue.",
        },
    }


def test_build_interrupt_lifecycle_message_contract_cases() -> None:
    for case in _MESSAGE_CASES:
        assert build_interrupt_lifecycle_message_code(case["event"]) == case["code"]
        assert (
            build_interrupt_lifecycle_message_content(case["event"]) == case["content"]
        )


def test_interrupt_event_block_content_round_trips_structured_payload() -> None:
    event = {
        "request_id": "perm-structured-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "read",
            "patterns": ["/repo/.env"],
            "display_message": "Agent requested permission: read.",
        },
    }

    serialized = serialize_interrupt_event_block_content(event)
    content, interrupt = deserialize_interrupt_event_block_content(serialized)

    assert content == "Agent requested permission: read.\nTargets: /repo/.env"
    assert interrupt == build_interrupt_block_view(event)
