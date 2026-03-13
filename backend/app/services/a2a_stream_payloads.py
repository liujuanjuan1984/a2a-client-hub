from __future__ import annotations

from typing import Any

from app.utils.payload_extract import as_dict


def _pick_non_empty_str(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pick_int(payload: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    return None


def extract_stream_text_from_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        raw_kind = part.get("kind") or part.get("type")
        normalized_kind = (
            raw_kind.strip().lower() if isinstance(raw_kind, str) else None
        )
        if normalized_kind not in {None, "", "text"}:
            continue
        text = part.get("text")
        if isinstance(text, str):
            collected.append(text)
            continue
        content = part.get("content")
        if isinstance(content, str):
            collected.append(content)
    return "".join(collected)


def extract_shared_stream_metadata(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    root_metadata = as_dict(payload.get("metadata"))
    artifact_metadata = as_dict(artifact.get("metadata"))
    for metadata in (root_metadata, artifact_metadata):
        shared = as_dict(metadata.get("shared"))
        stream = as_dict(shared.get("stream"))
        if stream:
            resolved.update(stream)
    return resolved


def extract_artifact_type(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    root_metadata = payload.get("metadata")
    if not isinstance(root_metadata, dict):
        root_metadata = {}
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    raw = shared_stream.get("block_type")
    if not isinstance(raw, str) or not raw.strip():
        raw = metadata.get("block_type")
    if not isinstance(raw, str) or not raw.strip():
        raw = root_metadata.get("block_type")

    if not isinstance(raw, str) or not raw.strip():
        if extract_stream_text_from_parts(artifact.get("parts")):
            return "text"
        return None

    normalized = raw.strip().lower()
    if normalized in {"text", "reasoning", "tool_call"}:
        return normalized
    return None


def extract_artifact_source(
    payload: dict[str, Any], artifact: dict[str, Any]
) -> str | None:
    metadata = artifact.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    root_metadata = payload.get("metadata")
    if not isinstance(root_metadata, dict):
        root_metadata = {}
    shared_stream = extract_shared_stream_metadata(payload, artifact)
    source = shared_stream.get("source")
    if not isinstance(source, str) or not source.strip():
        source = metadata.get("source")
    if not isinstance(source, str) or not source.strip():
        source = root_metadata.get("source")
    if isinstance(source, str) and source.strip():
        return source.strip().lower()
    return None


def extract_stream_sequence_from_serialized_event(
    payload: dict[str, Any],
) -> int | None:
    root = as_dict(payload)
    sequence = _pick_int(root, ("seq",))
    if sequence is not None:
        return sequence
    artifact = as_dict(root.get("artifact"))
    shared_stream = extract_shared_stream_metadata(root, artifact)
    return _pick_int(shared_stream, ("sequence", "seq"))


def extract_stream_chunk_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("kind") != "artifact-update":
        return None

    artifact = as_dict(payload.get("artifact"))
    if not artifact:
        return None
    artifact_metadata = as_dict(artifact.get("metadata"))
    root_metadata = as_dict(payload.get("metadata"))
    shared_stream = extract_shared_stream_metadata(payload, artifact)

    block_type = extract_artifact_type(payload, artifact)
    if block_type is None:
        return None

    event_id = None
    message_id = None
    for candidate in (
        payload,
        artifact,
        artifact_metadata,
        root_metadata,
        shared_stream,
    ):
        if event_id is None:
            event_id = _pick_non_empty_str(candidate, ("event_id", "eventId"))
        if message_id is None:
            message_id = _pick_non_empty_str(candidate, ("message_id", "messageId"))

    delta = extract_stream_text_from_parts(artifact.get("parts"))
    if not delta:
        return None

    append = payload.get("append")
    resolved_append = append if isinstance(append, bool) else True
    resolved_is_finished = (
        payload.get("lastChunk") is True
        or payload.get("last_chunk") is True
        or artifact.get("lastChunk") is True
        or artifact.get("last_chunk") is True
    )

    seq = (
        _pick_int(payload, ("seq",))
        or _pick_int(artifact, ("seq",))
        or _pick_int(artifact_metadata, ("seq",))
        or _pick_int(root_metadata, ("seq",))
        or _pick_int(shared_stream, ("sequence", "seq"))
    )
    source = extract_artifact_source(payload, artifact)
    return {
        "event_id": event_id,
        "seq": seq,
        "message_id": message_id,
        "block_type": block_type,
        "content": delta,
        "append": resolved_append,
        "is_finished": resolved_is_finished,
        "source": source,
    }


def analyze_stream_chunk_contract(
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if payload.get("kind") != "artifact-update":
        return None, None
    stream_block = extract_stream_chunk_from_serialized_event(payload)
    if stream_block is not None:
        return stream_block, None

    artifact = as_dict(payload.get("artifact"))
    if not artifact:
        return None, "missing_artifact"

    block_type = extract_artifact_type(payload, artifact)
    if block_type is None:
        return None, "missing_or_invalid_block_type"
    if extract_stream_text_from_parts(artifact.get("parts")) == "":
        return None, "missing_text_parts"
    return None, "invalid_artifact_update_shape"


def extract_interrupt_lifecycle_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("kind") != "status-update":
        return None

    status = as_dict(payload.get("status"))
    raw_state = _pick_non_empty_str(status, ("state",))
    metadata = as_dict(payload.get("metadata"))
    interrupt = as_dict(metadata.get("interrupt"))
    if not interrupt:
        return None

    request_id = _pick_non_empty_str(interrupt, ("request_id", "requestId"))
    interrupt_type = _pick_non_empty_str(interrupt, ("type",))
    if not request_id or interrupt_type not in {"permission", "question"}:
        return None

    phase = _pick_non_empty_str(interrupt, ("phase",))
    normalized_state = (raw_state or "").strip().lower()
    if phase is None:
        phase = (
            "asked"
            if normalized_state in {"input-required", "input_required"}
            else None
        )
    if phase not in {"asked", "resolved"}:
        return None

    payload_event: dict[str, Any] = {
        "request_id": request_id,
        "type": interrupt_type,
        "phase": phase,
    }
    if phase == "resolved":
        resolution = _pick_non_empty_str(interrupt, ("resolution",))
        if resolution not in {"replied", "rejected"}:
            return None
        payload_event["resolution"] = resolution
        return payload_event

    details = as_dict(interrupt.get("details")) or {}
    if interrupt_type == "permission":
        patterns = details.get("patterns")
        payload_event["details"] = {
            "permission": _pick_non_empty_str(details, ("permission",)),
            "patterns": (
                [item for item in patterns if isinstance(item, str)]
                if isinstance(patterns, list)
                else []
            ),
        }
        return payload_event

    questions = details.get("questions")
    normalized_questions: list[dict[str, Any]] = []
    if isinstance(questions, list):
        for entry in questions:
            candidate = as_dict(entry)
            if not candidate:
                continue
            question = _pick_non_empty_str(candidate, ("question",))
            if not question:
                continue
            raw_options = candidate.get("options")
            normalized_options: list[dict[str, Any]] = []
            if isinstance(raw_options, list):
                for raw_option in raw_options:
                    option = as_dict(raw_option)
                    if not option:
                        continue
                    label = _pick_non_empty_str(option, ("label",))
                    if not label:
                        continue
                    normalized_options.append(
                        {
                            "label": label,
                            "description": _pick_non_empty_str(
                                option, ("description",)
                            ),
                            "value": _pick_non_empty_str(option, ("value",)),
                        }
                    )
            normalized_questions.append(
                {
                    "header": _pick_non_empty_str(candidate, ("header",)),
                    "question": question,
                    "options": normalized_options,
                }
            )
    payload_event["details"] = {"questions": normalized_questions}
    return payload_event
