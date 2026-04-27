"""Lightweight validators for A2A payloads aligned with a2a-inspector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentCardValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_agent_card(card_data: dict[str, Any]) -> AgentCardValidationResult:
    """Validate the structure and fields of an agent card."""
    result = AgentCardValidationResult()

    required_fields = frozenset(
        [
            "name",
            "description",
            "supported_interfaces",
            "version",
            "capabilities",
            "default_input_modes",
            "default_output_modes",
            "skills",
        ]
    )

    for field_name in required_fields:
        if field_name not in card_data:
            result.errors.append(f"Required field is missing: '{field_name}'.")

    supported_interfaces = card_data.get("supported_interfaces")
    if supported_interfaces is not None:
        if not isinstance(supported_interfaces, list) or not supported_interfaces:
            result.errors.append(
                "Field 'supported_interfaces' must be a non-empty array."
            )
        else:
            for index, interface in enumerate(supported_interfaces):
                if not isinstance(interface, dict):
                    result.errors.append(
                        f"Interface {index} in 'supported_interfaces' must be an object."
                    )
                    continue
                url = interface.get("url")
                if not isinstance(url, str) or not (
                    url.startswith("http://") or url.startswith("https://")
                ):
                    result.errors.append(
                        "Each supported interface must declare an absolute 'url'."
                    )
                binding = interface.get("protocol_binding")
                if not isinstance(binding, str) or not binding.strip():
                    result.errors.append(
                        "Each supported interface must declare 'protocol_binding'."
                    )

    if "capabilities" in card_data and not isinstance(card_data["capabilities"], dict):
        result.errors.append("Field 'capabilities' must be an object.")

    for field_name in ["default_input_modes", "default_output_modes"]:
        if field_name in card_data:
            if not isinstance(card_data[field_name], list):
                result.errors.append(
                    f"Field '{field_name}' must be an array of strings."
                )
            elif not all(isinstance(item, str) for item in card_data[field_name]):
                result.errors.append(f"All items in '{field_name}' must be strings.")

    if "skills" in card_data:
        if not isinstance(card_data["skills"], list):
            result.errors.append(
                "Field 'skills' must be an array of AgentSkill objects."
            )
        elif not card_data["skills"]:
            result.warnings.append(
                "Field 'skills' array is empty. Agent must have at least one skill if it performs actions."
            )

    return result


def _validate_task(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "id" not in data:
        errors.append("Task object missing required field: 'id'.")
    if "status" not in data or "state" not in data.get("status", {}):
        errors.append("Task object missing required field: 'status.state'.")
    return errors


def _validate_status_update(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "status" not in data or "state" not in data.get("status", {}):
        errors.append("StatusUpdate object missing required field: 'status.state'.")
    return errors


def _validate_artifact_update(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "artifact" not in data:
        errors.append("ArtifactUpdate object missing required field: 'artifact'.")
    elif (
        "parts" not in data.get("artifact", {})
        or not isinstance(data.get("artifact", {}).get("parts"), list)
        or not data.get("artifact", {}).get("parts")
    ):
        errors.append("Artifact object must have a non-empty 'parts' array.")
    return errors


def _validate_message(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if (
        "parts" not in data
        or not isinstance(data.get("parts"), list)
        or not data.get("parts")
    ):
        errors.append("Message object must have a non-empty 'parts' array.")
    role = data.get("role")
    if role not in {"agent", "ROLE_AGENT"}:
        errors.append("Message from agent must have 'role' set to 'agent'.")
    return errors


def validate_message(data: dict[str, Any]) -> list[str]:
    """Validate an incoming message from the agent based on its kind."""
    if "kind" not in data:
        return ["Response from agent is missing required 'kind' field."]

    kind = data.get("kind")
    validators = {
        "task": _validate_task,
        "status-update": _validate_status_update,
        "artifact-update": _validate_artifact_update,
        "message": _validate_message,
    }

    validator = validators.get(str(kind))
    if validator:
        return validator(data)

    return [f"Unknown message kind received: '{kind}'."]
