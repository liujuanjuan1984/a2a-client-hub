"""Session feature API router for unified conversations."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.error_codes import status_code_for_extension_error_code
from app.api.routing import StrictAPIRouter
from app.db.models.conversation_thread import ConversationThread
from app.db.models.user import User
from app.db.transaction import commit_safely, load_for_external_call
from app.features.hub_agents.runtime import (
    HubA2ARuntimeNotFoundError,
    HubA2ARuntimeValidationError,
    HubA2AUserCredentialRequiredError,
    hub_a2a_runtime_builder,
)
from app.features.invoke.stream_payloads import extract_stream_text_from_parts
from app.features.personal_agents.runtime import (
    A2ARuntimeNotFoundError,
    A2ARuntimeValidationError,
    a2a_runtime_builder,
)
from app.features.self_management_shared.constants import (
    SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID,
    SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID,
)
from app.features.sessions.schemas import (
    SessionAppendMessageRequest,
    SessionAppendMessageResponse,
    SessionCancelResponse,
    SessionCommandRunRequest,
    SessionCommandRunResponse,
    SessionContinueResponse,
    SessionListResponse,
    SessionMessageBlocksQueryRequest,
    SessionMessageBlocksQueryResponse,
    SessionMessagesQueryRequest,
    SessionMessagesQueryResponse,
    SessionQueryRequest,
    SessionViewItem,
)
from app.features.sessions.service import session_hub_service
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.utils.session_identity import normalize_non_empty_text

router = StrictAPIRouter(prefix="/me/conversations", tags=["me-conversations"])

_UPSTREAM_ERRORS = {
    "upstream_bad_request",
    "upstream_client_error",
    "upstream_unreachable",
    "upstream_http_error",
    "upstream_server_error",
    "upstream_error",
    "runtime_invalid",
    "upstream_payload_error",
}
_FORBIDDEN_ERRORS = {"session_forbidden"}


def _status_code_for_session_error(detail: str) -> int:
    if detail == "session_not_found":
        return 404
    if detail == "message_not_found":
        return 404
    if detail == "block_not_found":
        return 404
    if detail == "upstream_resource_not_found":
        return 404
    if detail == "upstream_unauthorized":
        return 401
    if detail == "upstream_quota_exceeded":
        return 429
    if detail in {
        "append_requires_bound_session",
        "session_command_requires_bound_session",
    }:
        return 409
    if detail in _FORBIDDEN_ERRORS:
        return 403
    if detail == "upstream_permission_denied":
        return 403
    if detail in _UPSTREAM_ERRORS:
        if detail == "upstream_bad_request":
            return 400
        if detail == "upstream_unreachable":
            return 503
        return 502
    return 400


def _resolve_session_query_agent_id(agent_id: str | None) -> UUID | None:
    if agent_id is None:
        return None
    if agent_id == SELF_MANAGEMENT_BUILT_IN_AGENT_PUBLIC_ID:
        return SELF_MANAGEMENT_BUILT_IN_AGENT_INTERNAL_ID
    return UUID(agent_id)


def _build_command_display_content(
    *,
    command: str,
    arguments: str,
    prompt: str,
) -> str:
    normalized_command = command.strip()
    normalized_arguments = arguments.strip()
    normalized_prompt = prompt.strip()
    header = (
        f"{normalized_command} {normalized_arguments}"
        if normalized_arguments
        else normalized_command
    )
    return f"{header}\n{normalized_prompt}" if normalized_prompt else header


def _extract_session_command_result_item(
    result_payload: dict[str, Any] | None,
) -> tuple[str, str | None]:
    result = result_payload if isinstance(result_payload, dict) else {}
    item = result.get("item")
    if not isinstance(item, dict):
        raise HTTPException(status_code=502, detail="upstream_payload_error")

    response_text = extract_stream_text_from_parts(item.get("parts"))
    if not response_text.strip():
        raise HTTPException(status_code=502, detail="upstream_payload_error")

    upstream_message_id = None
    for key in ("messageId", "message_id"):
        raw_value = item.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            upstream_message_id = raw_value.strip()
            break
    return response_text, upstream_message_id


async def _get_conversation_thread_or_404(
    *,
    db: AsyncSession,
    user_id: UUID,
    conversation_id: str,
) -> ConversationThread:
    resolved_conversation_id = UUID(conversation_id)
    thread = cast(
        ConversationThread | None,
        await db.scalar(
            select(ConversationThread).where(
                and_(
                    ConversationThread.id == resolved_conversation_id,
                    ConversationThread.user_id == user_id,
                    ConversationThread.status == ConversationThread.STATUS_ACTIVE,
                )
            )
        ),
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return thread


async def _load_runtime_for_thread(
    *,
    db: AsyncSession,
    current_user: User,
    thread: ConversationThread,
) -> Any:
    agent_id = cast(UUID | None, thread.agent_id)
    agent_source = cast(str | None, thread.agent_source)
    if agent_source == "builtin":
        raise HTTPException(status_code=400, detail="runtime_invalid")
    if agent_id is None or agent_source not in {"personal", "shared"}:
        raise HTTPException(status_code=400, detail="runtime_invalid")

    current_user_id = cast(UUID, current_user.id)
    try:
        if agent_source == "shared":
            return await load_for_external_call(
                db,
                lambda session: hub_a2a_runtime_builder.build(
                    session,
                    user_id=current_user_id,
                    agent_id=agent_id,
                ),
            )
        return await load_for_external_call(
            db,
            lambda session: a2a_runtime_builder.build(
                session,
                user_id=current_user_id,
                agent_id=agent_id,
            ),
        )
    except (A2ARuntimeNotFoundError, HubA2ARuntimeNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HubA2AUserCredentialRequiredError as exc:
        raise HTTPException(
            status_code=403,
            detail=getattr(exc, "error_code", "credential_required"),
        ) from exc
    except (A2ARuntimeValidationError, HubA2ARuntimeValidationError) as exc:
        raise HTTPException(status_code=400, detail="runtime_invalid") from exc


def _build_session_action_metadata(
    *,
    thread: ConversationThread,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    provider = normalize_non_empty_text(cast(str | None, thread.external_provider))
    external_session_id = normalize_non_empty_text(
        cast(str | None, thread.external_session_id)
    )
    if provider and "provider" not in next_metadata:
        next_metadata["provider"] = provider
    if external_session_id and "externalSessionId" not in next_metadata:
        next_metadata["externalSessionId"] = external_session_id
    return next_metadata


@router.post(":query", response_model=SessionListResponse)
async def list_unified_sessions(
    *,
    payload: SessionQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionListResponse:
    current_user_id = cast(UUID, current_user.id)
    items, extra, db_mutated = await session_hub_service.list_sessions(
        db,
        user_id=current_user_id,
        page=payload.page,
        size=payload.size,
        source=payload.source,
        agent_id=_resolve_session_query_agent_id(payload.agent_id),
    )
    if db_mutated:
        await commit_safely(db)
    return SessionListResponse(
        items=[SessionViewItem.model_validate(item) for item in items],
        pagination=extra["pagination"],
    )


@router.post(
    "/{conversation_id}/messages:query",
    response_model=SessionMessagesQueryResponse,
)
async def list_unified_session_messages(
    *,
    conversation_id: str,
    payload: SessionMessagesQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionMessagesQueryResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        items, extra, db_mutated = await session_hub_service.list_messages(
            db,
            user_id=current_user_id,
            conversation_id=conversation_id,
            before=payload.before,
            limit=payload.limit,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionMessagesQueryResponse.model_validate(
        {
            "items": items,
            "pageInfo": extra["pageInfo"],
        }
    )


@router.post(
    "/{conversation_id}/messages:append",
    response_model=SessionAppendMessageResponse,
)
async def append_unified_session_message(
    *,
    conversation_id: str,
    payload: SessionAppendMessageRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionAppendMessageResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        thread = await _get_conversation_thread_or_404(
            db=db,
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
        runtime = await _load_runtime_for_thread(
            db=db,
            current_user=current_user,
            thread=thread,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_conversation_id") from exc

    external_session_id = normalize_non_empty_text(
        cast(str | None, thread.external_session_id)
    )
    if not external_session_id:
        raise HTTPException(status_code=409, detail="append_requires_bound_session")

    request_message_id = str(payload.user_message_id or uuid4())
    extensions_service = cast(Any, get_a2a_extensions_service())
    result = await extensions_service.append_session_control(
        runtime=runtime,
        session_id=external_session_id,
        request_payload={
            "parts": [{"type": "text", "text": payload.content.strip()}],
            "messageID": request_message_id,
        },
        metadata=_build_session_action_metadata(
            thread=thread,
            metadata=payload.metadata,
        ),
    )
    if not result.success:
        raise HTTPException(
            status_code=status_code_for_extension_error_code(result.error_code),
            detail=result.error_code or "upstream_error",
        )

    refs = await session_hub_service.record_user_message_by_local_session_id(
        db,
        local_session_id=cast(UUID, thread.id),
        user_id=current_user_id,
        content=payload.content.strip(),
        metadata={
            **_build_session_action_metadata(thread=thread, metadata=payload.metadata),
            "message_kind": "session_append_user",
        },
        idempotency_key=f"append:{request_message_id}",
        user_message_id=payload.user_message_id,
    )
    if not refs:
        raise HTTPException(status_code=404, detail="session_not_found")
    items, _db_mutated = await session_hub_service.get_message_items(
        db,
        user_id=current_user_id,
        conversation_id=conversation_id,
        message_ids=[refs["user_message_id"]],
    )
    await commit_safely(db)
    return SessionAppendMessageResponse.model_validate(
        {
            "conversationId": str(refs["conversation_id"]),
            "userMessage": items[0],
            "sessionControl": {
                "intent": "append",
                "status": "accepted",
                "sessionId": external_session_id,
            },
        }
    )


@router.post(
    "/{conversation_id}/commands:run",
    response_model=SessionCommandRunResponse,
)
async def run_unified_session_command(
    *,
    conversation_id: str,
    payload: SessionCommandRunRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionCommandRunResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        thread = await _get_conversation_thread_or_404(
            db=db,
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
        runtime = await _load_runtime_for_thread(
            db=db,
            current_user=current_user,
            thread=thread,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_conversation_id") from exc

    external_session_id = normalize_non_empty_text(
        cast(str | None, thread.external_session_id)
    )
    if not external_session_id:
        raise HTTPException(
            status_code=409,
            detail="session_command_requires_bound_session",
        )

    request_payload: dict[str, Any] = {
        "command": payload.command.strip(),
        "arguments": payload.arguments.strip(),
    }
    if payload.prompt.strip():
        request_payload["parts"] = [{"type": "text", "text": payload.prompt.strip()}]

    metadata = _build_session_action_metadata(
        thread=thread,
        metadata=payload.metadata,
    )
    extensions_service = cast(Any, get_a2a_extensions_service())
    result = await extensions_service.command_session(
        runtime=runtime,
        session_id=external_session_id,
        request_payload=request_payload,
        metadata=metadata,
    )
    if not result.success:
        raise HTTPException(
            status_code=status_code_for_extension_error_code(result.error_code),
            detail=result.error_code or "upstream_error",
        )

    response_text, upstream_message_id = _extract_session_command_result_item(
        cast(dict[str, Any] | None, result.result),
    )
    refs = await session_hub_service.record_local_invoke_messages_by_local_session_id(
        db,
        local_session_id=cast(UUID, thread.id),
        source=cast(Any, thread.source),
        user_id=current_user_id,
        agent_id=cast(UUID, thread.agent_id),
        agent_source=cast(Any, thread.agent_source),
        query=_build_command_display_content(
            command=payload.command,
            arguments=payload.arguments,
            prompt=payload.prompt,
        ),
        response_content=response_text,
        success=True,
        context_id=cast(str | None, thread.context_id),
        invoke_metadata=metadata,
        extra_metadata={
            "message_kind": "session_command_input",
            "session_command": {
                "command": payload.command.strip(),
                "arguments": payload.arguments.strip(),
            },
        },
        response_metadata={
            "message_kind": "session_command_output",
            "session_command": {
                "command": payload.command.strip(),
                "arguments": payload.arguments.strip(),
            },
            **(
                {"upstream_message_id": upstream_message_id}
                if upstream_message_id
                else {}
            ),
        },
        idempotency_key=(
            f"command:{payload.user_message_id}"
            if payload.user_message_id is not None
            else None
        ),
        user_message_id=payload.user_message_id,
        agent_message_id=payload.agent_message_id,
        agent_status="done",
    )
    if not refs:
        raise HTTPException(status_code=404, detail="session_not_found")

    items, _db_mutated = await session_hub_service.get_message_items(
        db,
        user_id=current_user_id,
        conversation_id=conversation_id,
        message_ids=[refs["user_message_id"], refs["agent_message_id"]],
    )
    await commit_safely(db)
    return SessionCommandRunResponse.model_validate(
        {
            "conversationId": str(refs["conversation_id"]),
            "userMessage": items[0],
            "agentMessage": items[1],
        }
    )


@router.post(
    "/{conversation_id}/blocks:query",
    response_model=SessionMessageBlocksQueryResponse,
)
async def list_unified_session_message_blocks(
    *,
    conversation_id: str,
    payload: SessionMessageBlocksQueryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionMessageBlocksQueryResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        items, db_mutated = await session_hub_service.list_message_blocks(
            db,
            user_id=current_user_id,
            conversation_id=conversation_id,
            block_ids=payload.block_ids,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionMessageBlocksQueryResponse.model_validate({"items": items})


@router.post("/{conversation_id}:continue", response_model=SessionContinueResponse)
async def continue_unified_session(
    *,
    conversation_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionContinueResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        payload, db_mutated = await session_hub_service.continue_session(
            db,
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionContinueResponse.model_validate(payload)


@router.post("/{conversation_id}/cancel", response_model=SessionCancelResponse)
async def cancel_unified_session(
    *,
    conversation_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SessionCancelResponse:
    current_user_id = cast(UUID, current_user.id)
    try:
        payload, db_mutated = await session_hub_service.cancel_session(
            db,
            user_id=current_user_id,
            conversation_id=conversation_id,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_code_for_session_error(detail),
            detail=detail,
        ) from exc
    if db_mutated:
        await commit_safely(db)
    return SessionCancelResponse.model_validate(payload)


__all__ = ["router"]
