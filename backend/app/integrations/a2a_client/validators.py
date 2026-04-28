"""Lightweight validators for A2A payloads aligned with a2a-inspector."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from a2a.types import AgentCard
from google.protobuf.descriptor import Descriptor, FieldDescriptor

_SUPPORTED_PROTOCOL_BINDINGS = frozenset({"JSONRPC", "HTTP+JSON", "GRPC"})
_CANONICAL_TASK_STATE_PREFIX = "TASK_STATE_"
_CANONICAL_AGENT_ROLE = "ROLE_AGENT"
_DYNAMIC_PROTO_FULL_NAMES = frozenset(
    {
        "google.protobuf.Struct",
        "google.protobuf.Value",
        "google.protobuf.ListValue",
        "google.protobuf.Timestamp",
        "google.protobuf.Empty",
    }
)

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
        (("supportedInterfaces",), "supportedInterfaces"),
        (("version",), "version"),
        (("capabilities",), "capabilities"),
        (("defaultInputModes",), "defaultInputModes"),
        (("defaultOutputModes",), "defaultOutputModes"),
        (("skills",), "skills"),
    )

    for candidate_names, display_name in required_fields:
        if _pick_first(card_data, *candidate_names) is None:
            result.errors.append(f"Required field is missing: '{display_name}'.")

    for path, canonical_name in _find_noncanonical_protojson_alias_paths(
        card_data,
        AgentCard.DESCRIPTOR,
    ):
        result.errors.append(
            f"Field '{path}' is not canonical ProtoJSON; use '{canonical_name}'."
        )

    for field_name, message in _LEGACY_TOP_LEVEL_FIELD_MESSAGES.items():
        if field_name in card_data:
            result.errors.append(message)

    supported_interfaces = _pick_first(card_data, "supportedInterfaces")
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
                binding = _pick_first(interface, "protocolBinding")
                if not isinstance(binding, str) or not binding.strip():
                    result.errors.append(
                        "Each supported interface must declare 'protocolBinding'."
                    )
                elif binding.strip() not in _SUPPORTED_PROTOCOL_BINDINGS:
                    result.errors.append(
                        "Each supported interface must declare a supported "
                        "'protocolBinding' (JSONRPC, HTTP+JSON, GRPC)."
                    )
                protocol_version = _pick_first(interface, "protocolVersion")
                if protocol_version is not None:
                    if (
                        isinstance(protocol_version, str)
                        and not protocol_version.strip()
                    ):
                        protocol_version = None
                    elif not isinstance(protocol_version, str):
                        result.errors.append(
                            "Each supported interface must declare a non-empty "
                            "'protocolVersion' when provided."
                        )
                    elif _is_legacy_protocol_version(protocol_version):
                        result.errors.append(
                            "Legacy A2A protocolVersion '0.3' is not supported; "
                            "upgrade the peer to A2A 1.0."
                        )

    capabilities = _pick_first(card_data, "capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        result.errors.append("Field 'capabilities' must be an object.")
        capabilities = None

    if isinstance(capabilities, dict):
        for field_name, message in _LEGACY_CAPABILITY_FIELD_MESSAGES.items():
            if field_name in capabilities:
                result.errors.append(message)
        extended_agent_card = _pick_first(capabilities, "extendedAgentCard")
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
        (("defaultInputModes",), "defaultInputModes"),
        (("defaultOutputModes",), "defaultOutputModes"),
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
    else:
        state = data.get("status", {}).get("state")
        if not _is_canonical_task_state(state):
            errors.append(
                "Task object must use canonical A2A 1.0 task states (TASK_STATE_*)."
            )
    return errors


def _validate_status_update(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "status" not in data or "state" not in data.get("status", {}):
        errors.append("StatusUpdate object missing required field: 'status.state'.")
    else:
        state = data.get("status", {}).get("state")
        if not _is_canonical_task_state(state):
            errors.append(
                "StatusUpdate object must use canonical A2A 1.0 task states (TASK_STATE_*)."
            )
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
    if role != _CANONICAL_AGENT_ROLE:
        errors.append(
            "Message from agent must have canonical A2A 1.0 role 'ROLE_AGENT'."
        )
    return errors


def validate_message(data: dict[str, Any]) -> list[str]:
    """Validate a canonical A2A 1.0 StreamResponse payload."""

    canonical_fields = {
        "task": _validate_task,
        "message": _validate_message,
        "statusUpdate": _validate_status_update,
        "artifactUpdate": _validate_artifact_update,
    }
    present_fields = [
        field_name for field_name in canonical_fields if field_name in data
    ]
    if not present_fields:
        return [
            "Response from agent must be a canonical A2A 1.0 StreamResponse payload."
        ]
    if len(present_fields) > 1:
        return [
            "StreamResponse payload must set exactly one of 'task', 'message', "
            "'statusUpdate', or 'artifactUpdate'."
        ]

    kind = present_fields[0]
    payload = data.get(kind)
    if not isinstance(payload, dict):
        return [f"Field '{kind}' must be an object."]

    validators = {
        "task": _validate_task,
        "message": _validate_message,
        "statusUpdate": _validate_status_update,
        "artifactUpdate": _validate_artifact_update,
    }

    validator = validators.get(str(kind))
    if validator:
        return validator(payload)

    return [f"Unknown StreamResponse field received: '{kind}'."]


def _pick_first(data: dict[str, Any], *field_names: str) -> Any:
    for field_name in field_names:
        if field_name in data:
            return data[field_name]
    return None


def _is_canonical_task_state(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_CANONICAL_TASK_STATE_PREFIX)


def _is_legacy_protocol_version(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("0.3")


def _find_noncanonical_protojson_alias_paths(
    payload: Any,
    descriptor: Descriptor,
    *,
    path: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    if not isinstance(payload, Mapping):
        return []

    field_by_name = {field.name: field for field in descriptor.fields}
    field_by_json_name = {field.json_name: field for field in descriptor.fields}
    aliases: list[tuple[str, str]] = []

    for raw_key, child in payload.items():
        key = str(raw_key)
        field = field_by_json_name.get(key)
        if field is None:
            field = field_by_name.get(key)
            if field is None:
                continue
            if field.json_name != key:
                aliases.append((_format_proto_path((*path, key)), field.json_name))

        if field.type != FieldDescriptor.TYPE_MESSAGE:
            continue

        nested_descriptor = field.message_type
        if nested_descriptor.full_name in _DYNAMIC_PROTO_FULL_NAMES:
            continue

        if field.label == FieldDescriptor.LABEL_REPEATED:
            if nested_descriptor.GetOptions().map_entry:
                value_field = nested_descriptor.fields_by_name.get("value")
                if (
                    value_field is None
                    or value_field.type != FieldDescriptor.TYPE_MESSAGE
                    or value_field.message_type.full_name in _DYNAMIC_PROTO_FULL_NAMES
                    or not isinstance(child, Mapping)
                ):
                    continue
                for map_key, map_value in child.items():
                    aliases.extend(
                        _find_noncanonical_protojson_alias_paths(
                            map_value,
                            value_field.message_type,
                            path=(*path, key, str(map_key)),
                        )
                    )
                continue

            if not isinstance(child, list):
                continue
            for index, item in enumerate(child):
                aliases.extend(
                    _find_noncanonical_protojson_alias_paths(
                        item,
                        nested_descriptor,
                        path=(*path, key, f"[{index}]"),
                    )
                )
            continue

        aliases.extend(
            _find_noncanonical_protojson_alias_paths(
                child,
                nested_descriptor,
                path=(*path, key),
            )
        )

    return aliases


def _format_proto_path(parts: tuple[str, ...]) -> str:
    if not parts:
        return ""
    formatted: list[str] = []
    for part in parts:
        if part.startswith("[") and formatted:
            formatted[-1] = f"{formatted[-1]}{part}"
            continue
        formatted.append(part)
    return ".".join(formatted)
