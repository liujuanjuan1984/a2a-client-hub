"""Lightweight validators for A2A payloads aligned with a2a-inspector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_SUPPORTED_PROTOCOL_BINDINGS = frozenset({"JSONRPC", "HTTP+JSON", "GRPC"})

_LEGACY_TOP_LEVEL_FIELD_MESSAGES = {
    "url": "Legacy field 'url' is not supported in A2A 1.0; use 'supportedInterfaces' instead.",
    "supports_authenticated_extended_card": (
        "Legacy field 'supports_authenticated_extended_card' is not supported in "
        "A2A 1.0; use 'capabilities.extendedAgentCard' instead."
    ),
    "supportsAuthenticatedExtendedCard": (
        "Legacy field 'supportsAuthenticatedExtendedCard' is not supported in "
        "A2A 1.0; use 'capabilities.extendedAgentCard' instead."
    ),
    "examples": (
        "Legacy field 'examples' is not supported in A2A 1.0; move examples to "
        "individual skills."
    ),
}

_LEGACY_CAPABILITY_FIELD_MESSAGES = {
    "input_modes": (
        "Legacy field 'capabilities.input_modes' is not supported in A2A 1.0; "
        "use 'defaultInputModes' or per-skill 'inputModes' instead."
    ),
    "inputModes": (
        "Legacy field 'capabilities.inputModes' is not supported in A2A 1.0; "
        "use 'defaultInputModes' or per-skill 'inputModes' instead."
    ),
    "output_modes": (
        "Legacy field 'capabilities.output_modes' is not supported in A2A 1.0; "
        "use 'defaultOutputModes' or per-skill 'outputModes' instead."
    ),
    "outputModes": (
        "Legacy field 'capabilities.outputModes' is not supported in A2A 1.0; "
        "use 'defaultOutputModes' or per-skill 'outputModes' instead."
    ),
}


@dataclass(slots=True)
class AgentCardValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_agent_card(card_data: dict[str, Any]) -> AgentCardValidationResult:
    """Validate the structure and fields of an agent card."""
    result = AgentCardValidationResult()

    required_fields = (
        (("name",), "name"),
        (("description",), "description"),
        (("supportedInterfaces", "supported_interfaces"), "supportedInterfaces"),
        (("version",), "version"),
        (("capabilities",), "capabilities"),
        (("defaultInputModes", "default_input_modes"), "defaultInputModes"),
        (("defaultOutputModes", "default_output_modes"), "defaultOutputModes"),
        (("skills",), "skills"),
    )

    for candidate_names, display_name in required_fields:
        if _pick_first(card_data, *candidate_names) is None:
            result.errors.append(f"Required field is missing: '{display_name}'.")

    for field_name, message in _LEGACY_TOP_LEVEL_FIELD_MESSAGES.items():
        if field_name in card_data:
            result.errors.append(message)

    supported_interfaces = _pick_first(
        card_data,
        "supportedInterfaces",
        "supported_interfaces",
    )
    if supported_interfaces is not None:
        if not isinstance(supported_interfaces, list) or not supported_interfaces:
            result.errors.append(
                "Field 'supportedInterfaces' must be a non-empty array."
            )
        else:
            for index, interface in enumerate(supported_interfaces):
                if not isinstance(interface, dict):
                    result.errors.append(
                        f"Interface {index} in 'supportedInterfaces' must be an object."
                    )
                    continue
                url = _pick_first(interface, "url")
                if not isinstance(url, str) or not (
                    url.startswith("http://") or url.startswith("https://")
                ):
                    result.errors.append(
                        "Each supported interface must declare an absolute 'url'."
                    )
                binding = _pick_first(interface, "protocolBinding", "protocol_binding")
                if not isinstance(binding, str) or not binding.strip():
                    result.errors.append(
                        "Each supported interface must declare 'protocolBinding'."
                    )
                elif binding.strip() not in _SUPPORTED_PROTOCOL_BINDINGS:
                    result.errors.append(
                        "Each supported interface must declare a supported "
                        "'protocolBinding' (JSONRPC, HTTP+JSON, GRPC)."
                    )

    capabilities = _pick_first(card_data, "capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        result.errors.append("Field 'capabilities' must be an object.")
        capabilities = None

    if isinstance(capabilities, dict):
        for field_name, message in _LEGACY_CAPABILITY_FIELD_MESSAGES.items():
            if field_name in capabilities:
                result.errors.append(message)
        extended_agent_card = _pick_first(
            capabilities,
            "extendedAgentCard",
            "extended_agent_card",
        )
        if extended_agent_card is not None and not isinstance(
            extended_agent_card, bool
        ):
            result.errors.append(
                "Field 'capabilities.extendedAgentCard' must be a boolean."
            )
        streaming = _pick_first(capabilities, "streaming")
        if streaming is not None and not isinstance(streaming, bool):
            result.errors.append("Field 'capabilities.streaming' must be a boolean.")

    for candidate_names, display_name in (
        (("defaultInputModes", "default_input_modes"), "defaultInputModes"),
        (("defaultOutputModes", "default_output_modes"), "defaultOutputModes"),
    ):
        value = _pick_first(card_data, *candidate_names)
        if value is not None:
            if not isinstance(value, list):
                result.errors.append(
                    f"Field '{display_name}' must be an array of strings."
                )
            elif not all(isinstance(item, str) for item in value):
                result.errors.append(f"All items in '{display_name}' must be strings.")

    skills = _pick_first(card_data, "skills")
    if skills is not None:
        if not isinstance(skills, list):
            result.errors.append(
                "Field 'skills' must be an array of AgentSkill objects."
            )
        elif not skills:
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


def _pick_first(data: dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        if field_name in data:
            return data[field_name]
    return None
