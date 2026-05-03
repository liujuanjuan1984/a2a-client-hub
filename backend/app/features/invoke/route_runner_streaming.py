"""Invoke route-runner stream diagnostics and persistence helpers."""

from __future__ import annotations

import time
from typing import Any, Callable, Literal
from uuid import UUID

from app.db.session import AsyncSessionLocal
from app.db.transaction import commit_safely
from app.features.invoke.payload_analysis import (
    extract_binding_hints_from_serialized_event,
    extract_stream_identity_hints_from_serialized_event,
    extract_usage_hints_from_serialized_event,
)
from app.features.invoke.payload_helpers import dict_field as _dict_field
from app.features.invoke.route_runner_state import (
    InvokeState,
    bind_inflight_task_if_needed,
    unregister_inflight_invoke,
)
from app.features.invoke.service_types import (
    StreamFinishReason,
    StreamOutcome,
)
from app.features.invoke.shared_metadata import extract_shared_metadata_section
from app.features.invoke.stream_payloads import (
    extract_interrupt_lifecycle_from_serialized_event,
    extract_stream_chunk_from_serialized_event,
)
from app.features.invoke.stream_persistence import (
    InvokePersistenceRequest,
    coerce_uuid,
)
from app.features.invoke.stream_persistence import (
    flush_stream_buffer as flush_stream_buffer_impl,
)
from app.features.invoke.stream_persistence import (
    persist_interrupt_lifecycle_event as persist_interrupt_lifecycle_event_impl,
)
from app.features.invoke.stream_persistence import (
    persist_local_outcome as persist_local_outcome_impl,
)
from app.features.invoke.stream_persistence import (
    persist_stream_block_update as persist_stream_block_update_impl,
)
from app.features.sessions.common import serialize_interrupt_event_block_content
from app.features.sessions.service import session_hub_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
)
from app.integrations.a2a_extensions.stream_hints import resolve_stream_hints
from app.utils.payload_extract import extract_provider_and_external_session_id

_STREAM_HINTS_WARNING_TTL_SECONDS = 300.0
_stream_hints_warning_cache: dict[
    tuple[str, tuple[tuple[str, str], ...], str],
    float,
] = {}


def collect_stream_hints(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
) -> None:
    (
        event_context_id,
        event_metadata,
    ) = extract_binding_hints_from_serialized_event(event_payload)
    from app.features.invoke.session_binding import merge_invoke_binding_state

    state.context_id, state.metadata = merge_invoke_binding_state(
        current_context_id=state.context_id,
        current_metadata=state.metadata,
        next_context_id=event_context_id,
        next_metadata=event_metadata,
    )
    identity_hints = extract_stream_identity_hints_from_serialized_event(event_payload)
    if identity_hints:
        state.stream_identity.update(identity_hints)
    usage_hints = extract_usage_hints_from_serialized_event(event_payload)
    if usage_hints:
        state.stream_usage = usage_hints


def log_stream_hints_warning(
    *,
    logger: Any,
    message: str,
    log_extra: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> None:
    log_warning = getattr(logger, "warning", None) or getattr(logger, "info", None)
    if not callable(log_warning):
        return
    merged_extra = dict(log_extra)
    if extra:
        merged_extra.update(extra)
    log_warning(message, extra=merged_extra)


def stream_hints_warning_cache_key(
    *,
    runtime: Any,
    warning_code: str,
) -> tuple[str, tuple[tuple[str, str], ...], str]:
    resolved = getattr(runtime, "resolved", None)
    url = str(getattr(resolved, "url", "") or "")
    headers = getattr(resolved, "headers", {}) or {}
    normalized_headers = tuple(
        sorted(
            (str(key), str(value))
            for key, value in headers.items()
            if isinstance(key, str) and isinstance(value, str)
        )
    )
    return url, normalized_headers, warning_code


def should_emit_stream_hints_warning(
    *,
    runtime: Any,
    warning_code: str,
) -> bool:
    now = time.monotonic()
    cache_key = stream_hints_warning_cache_key(
        runtime=runtime,
        warning_code=warning_code,
    )
    expires_at = _stream_hints_warning_cache.get(cache_key)
    if expires_at is not None and expires_at > now:
        return False
    _stream_hints_warning_cache[cache_key] = now + _STREAM_HINTS_WARNING_TTL_SECONDS
    return True


def build_stream_hints_runtime_meta_from_card(
    *,
    runtime: Any,
    card: Any,
    logger: Any,
    log_extra: dict[str, Any],
) -> dict[str, Any]:
    try:
        ext = resolve_stream_hints(card)
    except A2AExtensionNotSupportedError:
        meta = {
            "stream_hints_declared": False,
            "stream_hints_mode": "undeclared",
            "stream_hints_fallback_used": False,
        }
        if should_emit_stream_hints_warning(
            runtime=runtime,
            warning_code="stream_hints_unsupported",
        ):
            log_stream_hints_warning(
                logger=logger,
                message=(
                    "Stream hints extension not declared; "
                    "contract-only stream hints remain disabled"
                ),
                log_extra=log_extra,
                extra={"stream_hints_fallback_used": False},
            )
        return meta
    except A2AExtensionContractError as exc:
        meta = {
            "stream_hints_declared": True,
            "stream_hints_mode": "invalid_contract",
            "stream_hints_fallback_used": False,
            "stream_hints_contract_error": str(exc),
        }
        if should_emit_stream_hints_warning(
            runtime=runtime,
            warning_code=f"stream_hints_invalid:{str(exc)}",
        ):
            log_stream_hints_warning(
                logger=logger,
                message=(
                    "Stream hints contract invalid; "
                    "contract-only stream hints remain disabled"
                ),
                log_extra=log_extra,
                extra={
                    "stream_hints_contract_error": str(exc),
                    "stream_hints_fallback_used": False,
                },
            )
        return meta

    return {
        "stream_hints_declared": True,
        "stream_hints_uri": ext.uri,
        "stream_hints_mode": "declared_contract",
        "stream_hints_fallback_used": False,
    }


def build_stream_hints_session_started_callback(
    *,
    runtime: Any,
    state: InvokeState,
    logger: Any,
    log_extra: dict[str, Any],
    stream_log_extra: dict[str, Any],
) -> Callable[[Any], Any]:
    async def on_session_started(invoke_session: Any) -> None:
        snapshot = getattr(invoke_session, "snapshot", None)
        card = getattr(snapshot, "agent_card", None)
        if card is None:
            return
        state.stream_hints_meta = build_stream_hints_runtime_meta_from_card(
            runtime=runtime,
            card=card,
            logger=logger,
            log_extra=log_extra,
        )
        stream_log_extra.update(state.stream_hints_meta)

    return on_session_started


def has_shared_section(
    payload: dict[str, Any],
    *,
    section: str,
    include_artifact: bool = False,
    include_message: bool = False,
    include_status: bool = False,
    include_task: bool = False,
    include_result: bool = False,
) -> bool:
    candidates = [payload]
    if include_artifact:
        artifact_update = _dict_field(payload, "artifactUpdate")
        if artifact_update:
            candidates.append(artifact_update)
            artifact = _dict_field(artifact_update, "artifact")
            if artifact:
                candidates.append(artifact)
    if include_message:
        message = _dict_field(payload, "message")
        if message:
            candidates.append(message)
    if include_status:
        status_update = _dict_field(payload, "statusUpdate")
        if status_update:
            status = _dict_field(status_update, "status")
            if status:
                candidates.append(status)
            candidates.append(status_update)
    if include_task:
        task = _dict_field(payload, "task")
        if task:
            candidates.append(task)
    if include_result:
        result = _dict_field(payload, "result")
        if result:
            candidates.append(result)
    return any(
        bool(extract_shared_metadata_section(candidate, section=section))
        for candidate in candidates
        if candidate
    )


def warn_stream_hints_contract_gap_once(
    *,
    state: InvokeState,
    logger: Any,
    log_extra: dict[str, Any],
    key: str,
    message: str,
) -> None:
    if key in state.stream_hints_warned:
        return
    state.stream_hints_warned.add(key)
    log_stream_hints_warning(
        logger=logger,
        message=message,
        log_extra=log_extra,
        extra={
            "stream_hints_mode": state.stream_hints_meta.get("stream_hints_mode"),
            "stream_hints_contract_gap": key,
        },
    )


def diagnose_stream_hints_contract_gap(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
    logger: Any,
    log_extra: dict[str, Any],
) -> None:
    if state.stream_hints_meta.get("stream_hints_mode") != "declared_contract":
        return

    stream_chunk = extract_stream_chunk_from_serialized_event(event_payload)
    if stream_chunk and not has_shared_section(
        event_payload,
        section="stream",
        include_artifact=True,
    ):
        warn_stream_hints_contract_gap_once(
            state=state,
            logger=logger,
            log_extra=log_extra,
            key="shared_stream_missing",
            message=("Stream hints declared but event omitted metadata.shared.stream"),
        )

    usage_hints = extract_usage_hints_from_serialized_event(event_payload)
    if usage_hints and not has_shared_section(
        event_payload,
        section="usage",
        include_artifact=True,
        include_message=True,
        include_status=True,
        include_task=True,
        include_result=True,
    ):
        warn_stream_hints_contract_gap_once(
            state=state,
            logger=logger,
            log_extra=log_extra,
            key="shared_usage_missing",
            message=("Stream hints declared but event omitted metadata.shared.usage"),
        )

    interrupt = extract_interrupt_lifecycle_from_serialized_event(event_payload)
    if interrupt and not has_shared_section(
        event_payload,
        section="interrupt",
        include_status=True,
    ):
        warn_stream_hints_contract_gap_once(
            state=state,
            logger=logger,
            log_extra=log_extra,
            key="shared_interrupt_missing",
            message=(
                "Stream hints declared but event omitted metadata.shared.interrupt"
            ),
        )

    _, binding_metadata = extract_binding_hints_from_serialized_event(event_payload)
    provider, external_session_id = extract_provider_and_external_session_id(
        {"metadata": binding_metadata}
    )
    if (provider or external_session_id) and not has_shared_section(
        event_payload,
        section="session",
        include_message=True,
        include_result=True,
    ):
        warn_stream_hints_contract_gap_once(
            state=state,
            logger=logger,
            log_extra=log_extra,
            key="shared_session_missing",
            message=("Stream hints declared but event omitted metadata.shared.session"),
        )


def resolve_final_runtime_state(outcome: StreamOutcome) -> str:
    if outcome.success:
        return "TASK_STATE_COMPLETED"
    if outcome.finish_reason == StreamFinishReason.CLIENT_DISCONNECT:
        return "TASK_STATE_CANCELED"
    return "TASK_STATE_FAILED"


def build_persisted_finalization_ack_event(
    *,
    state: InvokeState,
    outcome: StreamOutcome,
) -> dict[str, Any] | None:
    agent_message_id = (
        coerce_uuid(state.message_refs.get("agent_message_id"))
        if isinstance(state.message_refs, dict)
        else None
    ) or coerce_uuid(state.agent_message_id)
    if agent_message_id is None:
        return None
    return {
        "statusUpdate": {
            "status": {"state": resolve_final_runtime_state(outcome)},
            "metadata": {
                "shared": {
                    "stream": {
                        "messageId": str(agent_message_id),
                        "completionPhase": "persisted",
                        "finishReason": outcome.finish_reason.value,
                        "success": outcome.success,
                    }
                }
            },
        },
    }


async def flush_stream_buffer(
    *,
    state: InvokeState,
    user_id: UUID,
) -> None:
    await flush_stream_buffer_impl(
        state=state,
        user_id=user_id,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def persist_stream_block_update(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
) -> None:
    await persist_stream_block_update_impl(
        state=state,
        event_payload=event_payload,
        request=request,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def persist_interrupt_lifecycle_event(
    *,
    state: InvokeState,
    event_payload: dict[str, Any],
    request: InvokePersistenceRequest,
) -> None:
    await persist_interrupt_lifecycle_event_impl(
        state=state,
        event_payload=event_payload,
        request=request,
        build_interrupt_message_content=serialize_interrupt_event_block_content,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


async def persist_local_outcome(
    *,
    state: InvokeState,
    outcome: StreamOutcome,
    request: InvokePersistenceRequest,
    response_metadata: dict[str, Any] | None = None,
) -> None:
    await persist_local_outcome_impl(
        state=state,
        outcome=outcome,
        request=request,
        response_metadata=response_metadata,
        session_factory=AsyncSessionLocal,
        commit_fn=commit_safely,
        session_hub=session_hub_service,
    )


def build_consume_stream_callbacks(
    *,
    state: InvokeState,
    request: InvokePersistenceRequest,
    logger: Any = None,
    log_extra: dict[str, Any] | None = None,
    diagnose_stream_hints_contract_gap_fn: Callable[..., None] = (
        diagnose_stream_hints_contract_gap
    ),
    collect_stream_hints_fn: Callable[..., None] = collect_stream_hints,
    bind_inflight_task_if_needed_fn: Callable[..., Any] = (
        bind_inflight_task_if_needed
    ),
    persist_stream_block_update_fn: Callable[..., Any] = persist_stream_block_update,
    persist_interrupt_lifecycle_event_fn: Callable[..., Any] = (
        persist_interrupt_lifecycle_event
    ),
    flush_stream_buffer_fn: Callable[..., Any] = flush_stream_buffer,
    persist_local_outcome_fn: Callable[..., Any] = persist_local_outcome,
    build_persisted_finalization_ack_event_fn: Callable[..., dict[str, Any] | None] = (
        build_persisted_finalization_ack_event
    ),
    unregister_inflight_invoke_fn: Callable[..., Any] = unregister_inflight_invoke,
) -> tuple[
    Callable[[dict[str, Any]], Any],
    Callable[[StreamOutcome], Any],
]:
    resolved_log_extra = log_extra if log_extra is not None else {}

    async def on_event(event_payload: dict[str, Any]) -> None:
        diagnose_stream_hints_contract_gap_fn(
            state=state,
            event_payload=event_payload,
            logger=logger,
            log_extra=resolved_log_extra,
        )
        collect_stream_hints_fn(state=state, event_payload=event_payload)
        await bind_inflight_task_if_needed_fn(state=state, user_id=request.user_id)
        await persist_stream_block_update_fn(
            state=state,
            event_payload=event_payload,
            request=request,
        )
        await persist_interrupt_lifecycle_event_fn(
            state=state,
            event_payload=event_payload,
            request=request,
        )

    async def on_finalized(outcome: StreamOutcome) -> dict[str, Any] | None:
        try:
            await flush_stream_buffer_fn(state=state, user_id=request.user_id)
            await persist_local_outcome_fn(
                state=state,
                outcome=outcome,
                request=request,
            )
            return build_persisted_finalization_ack_event_fn(
                state=state,
                outcome=outcome,
            )
        finally:
            await unregister_inflight_invoke_fn(state=state, user_id=request.user_id)

    return on_event, on_finalized


def build_invoke_persistence_request(
    *,
    user_id: UUID,
    agent_id: UUID,
    agent_source: Literal["personal", "shared"],
    query: str,
    transport: Literal["http_json", "http_sse", "scheduled", "ws"],
    stream_enabled: bool,
    user_sender: Literal["user", "automation"] = "user",
    extra_persisted_metadata: dict[str, Any] | None = None,
) -> InvokePersistenceRequest:
    return InvokePersistenceRequest(
        user_id=user_id,
        agent_id=agent_id,
        agent_source=agent_source,
        query=query,
        transport=transport,
        stream_enabled=stream_enabled,
        user_sender=user_sender,
        extra_persisted_metadata=dict(extra_persisted_metadata or {}),
    )
