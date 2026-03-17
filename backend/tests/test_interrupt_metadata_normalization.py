from app.services.a2a_stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
)
from app.services.session_hub_common import (
    build_interrupt_lifecycle_message_content,
    normalize_interrupt_lifecycle_event,
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


def test_build_interrupt_lifecycle_message_content_prefers_permission_display_text() -> (
    None
):
    event = {
        "request_id": "perm-1",
        "type": "permission",
        "phase": "asked",
        "details": {
            "permission": "approval",
            "patterns": ["/repo/.env"],
            "display_message": "Agent wants to read the environment file.",
        },
    }

    assert build_interrupt_lifecycle_message_content(event) == (
        "Agent wants to read the environment file.\nTargets: /repo/.env"
    )


def test_build_interrupt_lifecycle_message_content_keeps_question_details() -> None:
    event = {
        "request_id": "q-1",
        "type": "question",
        "phase": "asked",
        "details": {
            "display_message": "Please confirm how the agent should continue.",
            "questions": [
                {
                    "question": "Proceed with deployment?",
                    "description": "This will update the production service.",
                }
            ],
        },
    }

    assert build_interrupt_lifecycle_message_content(event) == (
        "Please confirm how the agent should continue.\n"
        "Question: Proceed with deployment?\n"
        "Details: This will update the production service."
    )
