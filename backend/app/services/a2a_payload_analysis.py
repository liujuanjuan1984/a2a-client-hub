from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.integrations.a2a_extensions.shared_contract import SHARED_STREAM_KEY
from app.services.a2a_shared_metadata import (
    extract_preferred_usage_metadata,
    merge_shared_metadata_sections,
)
from app.utils.payload_extract import (
    as_dict,
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

    direct_usage = as_dict(payload.get("usage"))
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
    root = as_dict(payload)

    artifact = as_dict(root.get("artifact"))
    artifact_metadata = as_dict(artifact.get("metadata"))
    message = as_dict(root.get("message"))
    message_metadata = as_dict(message.get("metadata"))
    status = as_dict(root.get("status"))
    status_metadata = as_dict(status.get("metadata"))
    task = as_dict(root.get("task"))
    task_status = as_dict(task.get("status"))
    task_status_metadata = as_dict(task_status.get("metadata"))
    result = as_dict(root.get("result"))
    result_status = as_dict(result.get("status"))
    result_status_metadata = as_dict(result_status.get("metadata"))
    root_metadata = as_dict(root.get("metadata"))
    artifact_shared_stream = merge_shared_metadata_sections(
        (root, artifact),
        section=SHARED_STREAM_KEY,
    )

    msg_id = None
    evt_id = None
    for cand in (
        root,
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
    ):
        if msg_id is None:
            msg_id = _pick_non_empty_str(cand, ("message_id", "messageId"))
        if evt_id is None:
            evt_id = _pick_non_empty_str(cand, ("event_id", "eventId"))

    task_id = _pick_non_empty_str(root, ("task_id", "taskId"))
    if task_id is None:
        for cand in (
            artifact,
            task,
            as_dict(result.get("task")),
            as_dict(status.get("task")),
            root_metadata,
        ):
            task_id = _pick_non_empty_str(cand, ("task_id", "taskId", "id"))
            if task_id:
                break

    seq = _pick_int(root, ("seq",))
    if seq is None:
        for cand in (
            artifact,
            artifact_metadata,
            root_metadata,
            artifact_shared_stream,
        ):
            seq = _pick_int(cand, ("seq", "sequence"))
            if seq is not None:
                break

    usage: dict[str, Any] = {}
    for cand in (root, artifact, message, status, task, result):
        cand_usage = _extract_usage_from_candidate(cand)
        if cand_usage:
            usage.update(cand_usage)

    context_id = None
    provider = None
    external_session_id = None
    binding_meta: dict[str, Any] = {}

    for cand in (root, message, result):
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

    if provider:
        binding_meta["provider"] = provider
    if external_session_id:
        binding_meta["externalSessionId"] = external_session_id

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
    if isinstance(resolved_payload, tuple):
        if len(resolved_payload) >= 2 and resolved_payload[1]:
            resolved_payload = resolved_payload[1]
        elif resolved_payload:
            resolved_payload = resolved_payload[0]
        else:
            return {}
    if isinstance(resolved_payload, dict):
        return dict(resolved_payload)
    if hasattr(resolved_payload, "model_dump"):
        try:
            dumped = resolved_payload.model_dump(exclude_none=True)
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
            continue
        content = part.get("content")
        if isinstance(content, str) and content.strip():
            collected.append(content)
    if collected:
        return "".join(collected)
    return None


def extract_preferred_text_from_payload(payload: Any) -> str | None:
    root = as_dict(payload)
    if not root:
        return None

    direct_text = _pick_non_empty_str(root, ("text", "content", "message"))
    if direct_text:
        return direct_text

    parts_text = _extract_text_from_parts(root.get("parts"))
    if parts_text:
        return parts_text

    artifact = as_dict(root.get("artifact"))
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
            entry_root = as_dict(entry)
            if not entry_root:
                continue
            role = _pick_non_empty_str(entry_root, ("role",))
            if role and role.lower() in {"agent", "assistant", "model"}:
                history_text = extract_preferred_text_from_payload(entry_root)
                if history_text:
                    return history_text
        for entry in reversed(history):
            history_text = extract_preferred_text_from_payload(entry)
            if history_text:
                return history_text

    for key in ("status", "result", "message"):
        nested = as_dict(root.get(key))
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
