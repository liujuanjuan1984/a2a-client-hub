from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.features.invoke import stream_payloads
from app.features.invoke.shared_metadata import (
    extract_preferred_usage_metadata,
    merge_preferred_session_binding_metadata,
    merge_shared_metadata_sections,
)
from app.integrations.a2a_client.protobuf import to_protojson_like
from app.integrations.a2a_extensions.shared_contract import SHARED_STREAM_KEY
from app.utils.payload_extract import (
    extract_context_id,
    extract_provider_and_external_session_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PayloadAnalysis:
    usage: dict[str, Any]
    upstream_message_id: str | None = None
    upstream_event_id: str | None = None
    upstream_event_seq: int | None = None
    upstream_task_id: str | None = None
    context_id: str | None = None
    binding_metadata: dict[str, Any] | None = None


def _dict_field(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _pick_non_empty_str(
    payload: dict[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _normalize_a2a_role(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("_", "-")
    if normalized.startswith("role-"):
        normalized = normalized[len("role-") :]
    return normalized or None


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


def _pick_number(payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                continue
            try:
                return float(raw)
            except ValueError:
                continue
    return None


def _extract_metadata_dict(payload: dict[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key in ("metadata", "bindingMetadata", "binding_metadata"):
        value = payload.get(key)
        if isinstance(value, dict):
            resolved.update(value)
    return resolved


def _extract_usage_from_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}

    direct_usage = _dict_field(payload, "usage")
    metadata_usage = extract_preferred_usage_metadata(payload)

    usage_payload: dict[str, Any] = {}
    if direct_usage:
        usage_payload.update(direct_usage)
    if metadata_usage:
        usage_payload.update(metadata_usage)
    if not usage_payload:
        return {}

    normalized: dict[str, Any] = {}
    token_field_map: dict[str, tuple[str, ...]] = {
        "input_tokens": ("input_tokens", "inputTokens"),
        "output_tokens": ("output_tokens", "outputTokens"),
        "total_tokens": ("total_tokens", "totalTokens"),
        "reasoning_tokens": ("reasoning_tokens", "reasoningTokens"),
        "cache_tokens": ("cache_tokens", "cacheTokens"),
    }
    for field_name, keys in token_field_map.items():
        value = _pick_int(usage_payload, keys)
        if value is not None and value >= 0:
            normalized[field_name] = value

    cost = _pick_number(usage_payload, ("cost",))
    if cost is not None and cost >= 0:
        normalized["cost"] = cost
    return normalized


def analyze_payload(payload: dict[str, Any]) -> PayloadAnalysis:
    root = payload if isinstance(payload, dict) else {}

    stream_kind, stream_body = stream_payloads._resolve_stream_response_body(root)
    event_metadata = _dict_field(stream_body, "metadata")
    artifact = stream_payloads._resolve_stream_artifact(root)
    artifact_metadata = _dict_field(artifact, "metadata")
    message = stream_body if stream_kind == "message" else _dict_field(root, "message")
    message_metadata = _dict_field(message, "metadata")
    status = (
        _dict_field(stream_body, "status")
        if stream_kind == "status-update"
        else _dict_field(root, "status")
    )
    status_metadata = _dict_field(status, "metadata")
    task = stream_body if stream_kind == "task" else _dict_field(root, "task")
    task_status = _dict_field(task, "status")
    task_status_metadata = _dict_field(task_status, "metadata")
    result = stream_body if stream_kind == "result" else _dict_field(root, "result")
    result_status = _dict_field(result, "status")
    result_status_metadata = _dict_field(result_status, "metadata")
    root_metadata = event_metadata if stream_body else _dict_field(root, "metadata")
    artifact_shared_stream = merge_shared_metadata_sections(
        tuple(
            candidate
            for candidate in ((stream_body if stream_body else root), artifact)
            if candidate
        ),
        section=SHARED_STREAM_KEY,
    )

    msg_id = None
    evt_id = None
    for cand in (
        artifact,
        artifact_metadata,
        message,
        message_metadata,
        status,
        status_metadata,
        task,
        task_status,
        task_status_metadata,
        result,
        result_status,
        result_status_metadata,
        artifact_shared_stream,
        root_metadata,
        stream_body,
    ):
        if msg_id is None:
            msg_id = _pick_non_empty_str(cand, ("messageId",))
        if evt_id is None:
            evt_id = _pick_non_empty_str(cand, ("eventId",))

    task_id = _pick_non_empty_str(stream_body, ("taskId",))
    if task_id is None:
        task_id = _pick_non_empty_str(task, ("id",))
    if task_id is None:
        task_id = _pick_non_empty_str(_dict_field(status, "task"), ("id",))
    if task_id is None:
        task_id = _pick_non_empty_str(_dict_field(result, "task"), ("id",))

    seq = _pick_int(stream_body, ("seq",))
    if seq is None:
        for cand in (
            artifact,
            artifact_metadata,
            root_metadata,
            artifact_shared_stream,
        ):
            seq = _pick_int(cand, ("seq",))
            if seq is not None:
                break

    usage: dict[str, Any] = {}
    for cand in (stream_body, artifact, message, status, task, result):
        cand_usage = _extract_usage_from_candidate(cand)
        if cand_usage:
            usage.update(cand_usage)

    context_id = None
    provider = None
    external_session_id = None
    binding_meta: dict[str, Any] = {}

    for cand in (stream_body, message, result):
        if context_id is None:
            context_id = extract_context_id(cand)

        c_meta = _extract_metadata_dict(cand)
        if c_meta:
            binding_meta.update(c_meta)

        if provider is None or external_session_id is None:
            c_provider, c_external = extract_provider_and_external_session_id(cand)
            if provider is None:
                provider = c_provider
            if external_session_id is None:
                external_session_id = c_external

    if context_id is None:
        context_id = extract_context_id(binding_meta)
    if provider is None or external_session_id is None:
        m_provider, m_external = extract_provider_and_external_session_id(binding_meta)
        if provider is None:
            provider = m_provider
        if external_session_id is None:
            external_session_id = m_external

    binding_meta = merge_preferred_session_binding_metadata(
        binding_meta,
        provider=provider,
        external_session_id=external_session_id,
    )

    return PayloadAnalysis(
        usage=usage,
        upstream_message_id=msg_id,
        upstream_event_id=evt_id,
        upstream_event_seq=seq,
        upstream_task_id=task_id,
        context_id=context_id,
        binding_metadata=binding_meta,
    )


def coerce_payload_to_dict(payload: Any) -> dict[str, Any]:
    resolved_payload = payload
    if isinstance(resolved_payload, dict):
        return dict(resolved_payload)
    try:
        dumped = to_protojson_like(resolved_payload)
    except Exception as exc:
        logger.error("Failed to dump A2A payload", exc_info=True)
        raise ValueError("Payload serialization failed") from exc
    if isinstance(dumped, dict):
        return dumped
    return {}


def extract_binding_hints_from_serialized_event(
    payload: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    analysis = analyze_payload(payload)
    return analysis.context_id, analysis.binding_metadata or {}


def extract_stream_identity_hints_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any]:
    analysis = analyze_payload(payload)
    hints: dict[str, Any] = {}
    if analysis.upstream_message_id:
        hints["upstream_message_id"] = analysis.upstream_message_id
    if analysis.upstream_event_id:
        hints["upstream_event_id"] = analysis.upstream_event_id
    if analysis.upstream_event_seq is not None:
        hints["upstream_event_seq"] = analysis.upstream_event_seq
    if analysis.upstream_task_id:
        hints["upstream_task_id"] = analysis.upstream_task_id
    return hints


def extract_usage_hints_from_serialized_event(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return analyze_payload(payload).usage


def extract_binding_hints_from_invoke_result(
    result: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    analysis = analyze_payload(result)
    context_id = analysis.context_id
    metadata = dict(analysis.binding_metadata or {})

    raw_payload = coerce_payload_to_dict(result.get("raw"))
    if raw_payload:
        raw_analysis = analyze_payload(raw_payload)
        if raw_analysis.context_id:
            context_id = raw_analysis.context_id
        if raw_analysis.binding_metadata:
            metadata.update(raw_analysis.binding_metadata)
    return context_id, metadata


def extract_stream_identity_hints_from_invoke_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    analysis = analyze_payload(result)
    hints: dict[str, Any] = {}
    if analysis.upstream_message_id:
        hints["upstream_message_id"] = analysis.upstream_message_id
    if analysis.upstream_event_id:
        hints["upstream_event_id"] = analysis.upstream_event_id
    if analysis.upstream_event_seq is not None:
        hints["upstream_event_seq"] = analysis.upstream_event_seq
    if analysis.upstream_task_id:
        hints["upstream_task_id"] = analysis.upstream_task_id

    raw_payload = coerce_payload_to_dict(result.get("raw"))
    if raw_payload:
        raw_analysis = analyze_payload(raw_payload)
        if raw_analysis.upstream_message_id:
            hints["upstream_message_id"] = raw_analysis.upstream_message_id
        if raw_analysis.upstream_event_id:
            hints["upstream_event_id"] = raw_analysis.upstream_event_id
        if raw_analysis.upstream_event_seq is not None:
            hints["upstream_event_seq"] = raw_analysis.upstream_event_seq
        if raw_analysis.upstream_task_id:
            hints["upstream_task_id"] = raw_analysis.upstream_task_id
    return hints


def extract_usage_hints_from_invoke_result(result: dict[str, Any]) -> dict[str, Any]:
    analysis = analyze_payload(result)
    usage_hints = analysis.usage

    raw_payload = coerce_payload_to_dict(result.get("raw"))
    if raw_payload:
        raw_analysis = analyze_payload(raw_payload)
        if raw_analysis.usage:
            usage_hints = raw_analysis.usage
    return usage_hints


def _extract_text_from_parts(parts: Any) -> str | None:
    if not isinstance(parts, list):
        return None
    collected: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            collected.append(text)
    if collected:
        return "".join(collected)
    return None


def extract_preferred_text_from_payload(payload: Any) -> str | None:
    root = payload if isinstance(payload, dict) else {}
    if not root:
        return None

    direct_text = _pick_non_empty_str(root, ("text",))
    if direct_text:
        return direct_text

    parts_text = _extract_text_from_parts(root.get("parts"))
    if parts_text:
        return parts_text

    artifact = _dict_field(root, "artifact")
    if artifact:
        artifact_text = _extract_text_from_parts(artifact.get("parts"))
        if artifact_text:
            return artifact_text

    artifacts = root.get("artifacts")
    if isinstance(artifacts, list):
        for artifact_item in reversed(artifacts):
            artifact_text = extract_preferred_text_from_payload(artifact_item)
            if artifact_text:
                return artifact_text

    history = root.get("history")
    if isinstance(history, list):
        for entry in reversed(history):
            entry_root = entry if isinstance(entry, dict) else {}
            if not entry_root:
                continue
            role = _normalize_a2a_role(_pick_non_empty_str(entry_root, ("role",)))
            if role == "agent":
                history_text = extract_preferred_text_from_payload(entry_root)
                if history_text:
                    return history_text

    for key in ("status", "result", "message"):
        nested = _dict_field(root, key)
        if nested:
            nested_text = extract_preferred_text_from_payload(nested)
            if nested_text:
                return nested_text

    return None


def extract_readable_content_from_invoke_result(result: dict[str, Any]) -> str | None:
    raw_payload = coerce_payload_to_dict(result.get("raw"))
    if raw_payload:
        raw_text = extract_preferred_text_from_payload(raw_payload)
        if raw_text:
            return raw_text

    content = result.get("content")
    if isinstance(content, str) and content.strip():
        stripped = content.strip()
        if stripped[:1] in {"{", "["}:
            try:
                parsed = json.loads(stripped)
            except Exception:
                return stripped
            parsed_text = extract_preferred_text_from_payload(parsed)
            if parsed_text:
                return parsed_text
        return stripped
    return None
