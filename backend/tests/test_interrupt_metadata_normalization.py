import json
from pathlib import Path

from app.services.a2a_stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
)
from app.services.session_hub_common import (
    build_interrupt_lifecycle_message_code,
    build_interrupt_lifecycle_message_content,
    normalize_interrupt_lifecycle_event,
)

_MESSAGE_CASES = json.loads(
    (
        Path(__file__).resolve().parents[2]
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


def test_extract_interrupt_lifecycle_falls_back_to_codex_private_permission_details() -> (
    None
):
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
            "patterns": ["/repo/.env"],
            "display_message": "Agent wants to read the environment file.",
        },
    }


def test_extract_interrupt_lifecycle_falls_back_to_codex_private_question_details() -> (
    None
):
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
            "display_message": "Please confirm how the agent should continue.",
            "questions": [
                {
                    "header": "Deploy",
                    "question": "Proceed with deployment?",
                    "description": None,
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
