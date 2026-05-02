from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.features.invoke import stream_payloads
from app.features.invoke.payload_helpers import dict_field as _dict_field
from app.features.invoke.payload_helpers import (
    pick_first_int,
    pick_first_non_empty_str,
)
from app.features.invoke.payload_helpers import pick_int as _pick_int
from app.features.invoke.shared_metadata import (
    extract_preferred_usage_metadata,
    merge_preferred_session_binding_metadata,
)
from app.integrations.a2a_client.protobuf import (
    to_protojson_object,
)
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
    root = payload

    content_envelope = stream_payloads.resolve_stream_content_envelope(root)
    stream_kind = content_envelope.event_kind
    stream_body = content_envelope.event_body
    event_metadata = content_envelope.event_metadata
    artifact = content_envelope.artifact
    artifact_metadata = content_envelope.artifact_metadata
    message = stream_body if stream_kind == "message" else _dict_field(root, "message")
    message_metadata = _dict_field(message, "metadata")
    status = (
        content_envelope.status
        if stream_kind == "status-update"
        else _dict_field(root, "status")
    )
    status_metadata = _dict_field(status, "metadata")
    status_message = content_envelope.status_message
    status_message_metadata = _dict_field(status_message, "metadata")
    task = stream_body if stream_kind == "task" else _dict_field(root, "task")
    task_status = _dict_field(task, "status")
    task_status_metadata = _dict_field(task_status, "metadata")
    result = stream_body if stream_kind == "result" else _dict_field(root, "result")
    result_status = _dict_field(result, "status")
    result_status_metadata = _dict_field(result_status, "metadata")
    root_metadata = event_metadata if stream_body else _dict_field(root, "metadata")
    artifact_shared_stream = content_envelope.shared_stream

    identity_candidates = (
        artifact,
        artifact_metadata,
        message,
        message_metadata,
        status,
        status_metadata,
        status_message,
        status_message_metadata,
        task,
        task_status,
        task_status_metadata,
        result,
        result_status,
        result_status_metadata,
        artifact_shared_stream,
        root_metadata,
        stream_body,
    )
    msg_id = pick_first_non_empty_str(identity_candidates, ("messageId",))
    evt_id = pick_first_non_empty_str(identity_candidates, ("eventId",))

    task_id = pick_first_non_empty_str(
        (
            stream_body,
            status_message,
            task,
            _dict_field(status, "task"),
            _dict_field(result, "task"),
        ),
        ("taskId", "id"),
    )

    seq = pick_first_int(
        (
            stream_body,
            artifact,
            artifact_metadata,
            root_metadata,
            artifact_shared_stream,
        ),
        ("seq",),
    )

    usage: dict[str, Any] = {}
    for cand in (stream_body, artifact, message, status_message, status, task, result):
        cand_usage = _extract_usage_from_candidate(cand)
        if cand_usage:
            usage.update(cand_usage)

    context_id = None
    provider = None
    external_session_id = None
    binding_meta: dict[str, Any] = {}

    for cand in (stream_body, message, status_message, result):
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
        dumped = to_protojson_object(resolved_payload)
    except Exception as exc:
        logger.error("Failed to dump A2A payload", exc_info=True)
        raise ValueError("Payload serialization failed") from exc
    if dumped is not None:
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
