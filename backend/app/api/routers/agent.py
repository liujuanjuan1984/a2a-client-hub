"""HTTP router exposing agent chat operations."""

import sys
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from card_box_core.structures import CardBox
from fastapi import Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import ROOT_AGENT_NAME, agent_registry
from app.agents.chat_service import ChatServiceError, chat_service
from app.agents.multi_agent import multi_agent_service
from app.agents.session_service import SessionServiceError, session_service
from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.cardbox.context_service import context_box_manager
from app.cardbox.service import cardbox_service
from app.cardbox.utils import tenant_for_user
from app.core.logging import get_logger, log_exception
from app.schemas.agent import (
    AgentProfileSummary,
    AgentRegistryListResponse,
    ToolArgumentSummary,
    ToolGuideSummary,
)
from app.schemas.agent_message import (
    ChatHistoryResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from app.schemas.cardbox import (
    ContextBoxSummary,
    SessionContextBox,
    SessionContextSelectionRequest,
    SessionContextSelectionResponse,
    SessionContextStateResponse,
)
from app.schemas.multi_agent import (
    AgentInvocationRequest,
    AgentInvocationResponse,
    NoteSummaryRequest,
    NoteSummaryResponse,
)
from app.schemas.session import (
    CreateSessionRequest,
    SessionListResponse,
    SessionResponse,
    UpdateSessionRequest,
)
from app.services.session_context_service import session_context_service
from app.services.token_quota_service import DailyTokenQuotaExceededError
from app.utils.json_encoder import json_dumps

logger = get_logger(__name__)

router = StrictAPIRouter()


MAX_CONTEXT_PREVIEW_CARDS = 120


def _extract_translation_pair(value: Any) -> Tuple[str, str]:
    """Return (zh, en) strings even when the source is plain text."""

    if value is None:
        return "", ""
    if isinstance(value, str):
        text = value.strip()
        return text, text

    zh = getattr(value, "zh", None)
    en = getattr(value, "en", None)

    if zh is None and en is None:
        fallback = str(value)
        return fallback, fallback

    zh_text = str(zh) if zh is not None else str(en or "")
    en_text = str(en) if en is not None else str(zh or "")
    return zh_text, en_text


@router.get("/agent/registry", response_model=AgentRegistryListResponse)
async def list_agents() -> AgentRegistryListResponse:
    """Return the list of available agents and their summaries."""

    summaries: List[AgentProfileSummary] = []
    for profile in agent_registry.list_profiles():
        tool_guides_payload: List[ToolGuideSummary] = []
        sequence = profile.tool_sequence or sorted(profile.explicit_tools)
        for tool_name in sequence:
            guide = profile.tool_guides.get(tool_name)
            if guide is None:
                continue
            arguments: List[ToolArgumentSummary] = []
            for arg in guide.arguments:
                desc_zh, desc_en = _extract_translation_pair(
                    getattr(arg, "description", "")
                )
                arguments.append(
                    ToolArgumentSummary(
                        name=arg.name,
                        type_hint=arg.type_hint,
                        required=arg.required,
                        description_zh=desc_zh,
                        description_en=desc_en,
                        default=getattr(arg, "default", None),
                    )
                )

            triggers_zh: List[str] = []
            triggers_en: List[str] = []
            for trigger in guide.triggers:
                zh_text, en_text = _extract_translation_pair(
                    getattr(trigger, "text", "")
                )
                triggers_zh.append(zh_text)
                triggers_en.append(en_text)

            purpose_zh, purpose_en = _extract_translation_pair(
                getattr(guide, "purpose", "")
            )
            tool_guides_payload.append(
                ToolGuideSummary(
                    name=guide.name,
                    purpose_zh=purpose_zh,
                    purpose_en=purpose_en,
                    arguments=arguments,
                    example=guide.example_json(),
                    triggers_zh=triggers_zh,
                    triggers_en=triggers_en,
                )
            )

        summaries.append(
            AgentProfileSummary(
                name=profile.name,
                description=profile.description,
                tools=sorted(profile.explicit_tools),
                allow_unassigned_tools=profile.allow_unassigned_tools,
                system_prompt_en=profile.system_prompt_en,
                prompt_version=profile.prompt_version,
                tool_guides=tool_guides_payload,
            )
        )
    total = len(summaries)
    pages = 1 if total > 0 else 0
    return AgentRegistryListResponse(
        items=summaries,
        pagination={
            "page": 1,
            "size": total,
            "total": total,
            "pages": pages,
        },
        meta={"source": "agent_registry"},
    )


def _context_record_to_summary(record) -> ContextBoxSummary:
    return ContextBoxSummary(
        box_id=record.box_id,
        name=record.name,
        module=record.module,
        display_name=record.display_name,
        card_count=record.card_count,
        updated_at=record.updated_at,
        metadata=record.manifest_metadata,
    )


def _build_combined_card_box(
    *,
    tenant_id: str,
    ordered_records: List[ContextBoxSummary],
    user_id: UUID,
) -> Tuple[CardBox, List[str]]:
    cardbox_service._get_engine(tenant_id)
    combined = CardBox()
    collected: List[str] = []
    for summary in ordered_records:
        skip_manifest = summary.module != "unknown"
        cards = context_box_manager.load_box_cards(
            user_id=user_id,
            box_name=summary.name,
            skip_manifest=skip_manifest,
            limit=None,
        )
        for card in cards:
            combined.add(card.card_id)
            collected.append(card.card_id)
            if len(combined.card_ids) >= MAX_CONTEXT_PREVIEW_CARDS:
                break
        if len(combined.card_ids) >= MAX_CONTEXT_PREVIEW_CARDS:
            break
    return combined, collected


@router.post("/agent/chat", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
    stream: bool = Query(False, description="Set to true for SSE streaming responses."),
) -> SendMessageResponse:
    """
    Send a message to the agent and get a response
    """
    logger.info(f"Received request with session_id: {request.session_id}")
    agent_name = request.agent_name or ROOT_AGENT_NAME
    if stream:
        try:
            message_stream = await chat_service.stream_message(
                db=db,
                user=current_user,
                content=request.content,
                session_id=request.session_id,
                agent_name=agent_name,
            )
        except DailyTokenQuotaExceededError as exc:
            raise HTTPException(
                status_code=429,
                detail=_build_quota_error_payload(exc),
            ) from exc
        except ChatServiceError as e:
            logger.error(f"Chat service error in streaming: {str(e)}")
            log_exception(
                logger, "Agent router ChatServiceError details", sys.exc_info()
            )
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            logger.error(f"Unexpected error in streaming send_message: {str(e)}")
            log_exception(
                logger,
                "Agent router unexpected error details",
                sys.exc_info(),
            )
            raise HTTPException(status_code=500, detail=str(e)) from e

        async def event_generator():
            try:
                logger.info(
                    f"Starting SSE stream for user {current_user.id}, session {request.session_id}"
                )

                try:
                    event_count = 0
                    async for event in message_stream:
                        event_count += 1
                        logger.debug(
                            f"Yielding SSE event #{event_count}: {event.get('event', 'unknown')}"
                        )
                        yield f"data: {json_dumps(event, ensure_ascii=False)}\n\n"
                    logger.info(f"Completed SSE stream after {event_count} events")
                except Exception as stream_error:
                    logger.error(
                        f"Error during message streaming after {event_count} events: {str(stream_error)}"
                    )
                    log_exception(
                        logger, "Message stream error details", sys.exc_info()
                    )
                    yield (
                        "event: error\n"
                        f"data: {json_dumps({'message': f'Stream interrupted: {str(stream_error)}'}, ensure_ascii=False)}\n\n"
                    )
                finally:
                    # Ensure proper stream termination
                    try:
                        yield "event: stream_end\ndata: {}\n\n"
                        logger.debug("Sent stream_end event")
                    except Exception:
                        logger.warning("Failed to send stream_end event")

            except ChatServiceError as e:
                logger.error(f"Chat service error in streaming: {str(e)}")
                log_exception(
                    logger, "Agent router ChatServiceError details", sys.exc_info()
                )
                yield (
                    "event: error\n"
                    f"data: {json_dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
                )
            except Exception as e:
                logger.error(f"Unexpected error in streaming send_message: {str(e)}")
                log_exception(
                    logger,
                    "Agent router unexpected error details",
                    sys.exc_info(),
                )
                yield (
                    "event: error\n"
                    f"data: {json_dumps({'message': f'Failed to stream message: {str(e)}'}, ensure_ascii=False)}\n\n"
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering
            },
        )

    try:
        response = await chat_service.send_message(
            db=db,
            user=current_user,
            content=request.content,
            session_id=request.session_id,
            agent_name=agent_name,
        )
        return response
    except DailyTokenQuotaExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail=_build_quota_error_payload(exc),
        ) from exc
    except ChatServiceError as e:
        log_exception(logger, f"Chat service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in send_message: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


@router.post("/agent/multi/note-summary", response_model=NoteSummaryResponse)
async def summarise_notes(
    request: NoteSummaryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> NoteSummaryResponse:
    """Trigger the multi-agent note summarisation workflow."""

    task = await multi_agent_service.summarise_notes(
        db=db,
        user_id=current_user.id,
        request_text=request.query,
        limit=request.limit,
        keyword=request.keyword,
    )

    result = task.final_result or {}
    summary = result.get("summary") or ""
    notes = result.get("notes") or []
    note_count = int(result.get("note_count") or len(notes))

    return NoteSummaryResponse(
        task_id=task.id,
        summary=summary,
        notes=notes,
        note_count=note_count,
    )


@router.post("/agent/multi/agent-call", response_model=AgentInvocationResponse)
async def invoke_specialist_agent(
    request: AgentInvocationRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> AgentInvocationResponse:
    if request.agent_name == ROOT_AGENT_NAME:
        raise HTTPException(status_code=400, detail="Root agent 不能通过此接口直接调用")

    profile = agent_registry.get_profile(request.agent_name)
    if profile.name != request.agent_name:
        raise HTTPException(status_code=404, detail="未找到指定的专属 Agent")

    try:
        task = await multi_agent_service.invoke_agent(
            db=db,
            user_id=current_user.id,
            agent_name=request.agent_name,
            instruction=request.instruction,
            tool_name=request.tool_name,
            tool_args=request.tool_args,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result_payload = task.final_result or {}
    return AgentInvocationResponse(
        task_id=task.id,
        agent_name=request.agent_name,
        tool_name=result_payload.get("tool_name") or request.tool_name or "",
        tool_args=result_payload.get("tool_args") or request.tool_args or {},
        result=result_payload.get("result") or {},
    )


@router.get("/agent/history", response_model=ChatHistoryResponse)
async def get_chat_history(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(50, ge=1, le=200, description="Page size"),
    session_id: Optional[UUID] = Query(
        None, description="Filter messages by session ID"
    ),
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> ChatHistoryResponse:
    """
    Get chat history
    """
    try:
        offset = (page - 1) * size
        messages, total_count = await chat_service.get_chat_history(
            db=db,
            user_id=current_user.id,
            limit=size,
            offset=offset,
            session_id=session_id,
        )

        pages = (total_count + size - 1) // size if size else 0
        return ChatHistoryResponse(
            items=messages,
            pagination={
                "page": page,
                "size": size,
                "total": total_count,
                "pages": pages,
            },
            meta={},
        )
    except ChatServiceError as e:
        log_exception(logger, f"Chat service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in get_chat_history: {str(e)}", sys.exc_info()
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to get chat history: {str(e)}"
        )


@router.delete("/agent/history")
async def clear_chat_history(
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Dict[str, str]:
    """
    Clear all chat history
    """
    try:
        deleted_count = await chat_service.clear_chat_history(
            db=db, user_id=current_user.id
        )

        return {
            "message": "Chat history cleared successfully",
            "deleted_count": deleted_count,
        }
    except ChatServiceError as e:
        log_exception(logger, f"Chat service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in clear_chat_history: {str(e)}", sys.exc_info()
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to clear chat history: {str(e)}"
        )


@router.delete("/agent/history/{session_id}")
async def clear_session_history(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Dict[str, str]:
    """
    Clear chat history for a specific session
    """
    try:
        deleted_count = await chat_service.clear_session_history(
            db=db, user_id=current_user.id, session_id=session_id
        )

        return {
            "message": "Session history cleared successfully",
            "deleted_count": deleted_count,
        }
    except ChatServiceError as e:
        log_exception(logger, f"Chat service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger,
            f"Unexpected error in clear_session_history: {str(e)}",
            sys.exc_info(),
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to clear session history: {str(e)}"
        )


@router.post(
    "/agent/context/session",
    response_model=SessionContextSelectionResponse,
)
async def set_session_context(
    payload: SessionContextSelectionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    session = await session_service.get_session(
        db=db,
        session_id=payload.session_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    clean_ids: List[int] = []
    seen: set[int] = set()

    session_box_name = cardbox_service.ensure_session_box(session)
    session_record = context_box_manager.get_record_by_name(
        user_id=current_user.id, name=session_box_name
    )
    if session_record:
        seen.add(session_record.box_id)
        clean_ids.append(session_record.box_id)

    for box_id in payload.box_ids:
        if box_id in seen:
            continue
        seen.add(box_id)
        clean_ids.append(box_id)

    await session_context_service.save_selection(
        db,
        user_id=current_user.id,
        session_id=payload.session_id,
        box_ids=clean_ids,
    )

    summaries: List[ContextBoxSummary] = []
    for order, box_id in enumerate(clean_ids):
        record = context_box_manager.get_record_by_id(
            user_id=current_user.id, box_id=box_id
        )
        if record is None:
            raise HTTPException(status_code=404, detail=f"CardBox {box_id} not found")
        summary = _context_record_to_summary(record)
        summaries.append(summary)

    tenant_id = tenant_for_user(current_user.id)
    combined_box, collected_ids = _build_combined_card_box(
        tenant_id=tenant_id,
        ordered_records=summaries,
        user_id=current_user.id,
    )

    preview_messages: List[Dict[str, Any]] = []
    source_card_ids: List[str] = []
    if combined_box.card_ids:
        engine = cardbox_service._get_engine(tenant_id)
        try:
            api_payload, used_card_ids = engine.to_api(combined_box)
            preview_messages = api_payload.get("messages", []) if api_payload else []
            source_card_ids = list(used_card_ids or [])
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to build combined context preview")
            preview_messages = []
            source_card_ids = list(collected_ids)
    else:
        source_card_ids = []

    response_boxes = [
        SessionContextBox(box=summary, order=index)
        for index, summary in enumerate(summaries)
    ]

    return SessionContextSelectionResponse(
        session_id=payload.session_id,
        boxes=response_boxes,
        preview_messages=preview_messages,
        source_card_ids=source_card_ids,
    )


@router.get(
    "/agent/context/session/state",
    response_model=SessionContextStateResponse,
)
async def get_session_context_state(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
):
    session = await session_service.get_session(
        db=db,
        session_id=session_id,
        user_id=current_user.id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    stored = await session_context_service.load_selection(
        db,
        user_id=current_user.id,
        session_id=session_id,
    )
    boxes: List[SessionContextBox] = []
    for entry in stored:
        record = context_box_manager.get_record_by_id(
            user_id=current_user.id, box_id=entry.get("box_id")
        )
        if record is None:
            continue
        summary = _context_record_to_summary(record)
        boxes.append(SessionContextBox(box=summary, order=entry.get("order", 0)))

    session_box_name = cardbox_service.ensure_session_box(session)
    session_record = context_box_manager.get_record_by_name(
        user_id=current_user.id, name=session_box_name
    )
    if session_record:
        has_session_box = any(box.box.box_id == session_record.box_id for box in boxes)
        if not has_session_box:
            summary = _context_record_to_summary(session_record)
            boxes.append(SessionContextBox(box=summary, order=0))

    boxes.sort(key=lambda item: item.order)
    return SessionContextStateResponse(session_id=session_id, boxes=boxes)


# Session Management Endpoints
@router.post("/agent/sessions", response_model=SessionResponse)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> SessionResponse:
    """
    Create a new chat session
    """
    try:
        session = await session_service.create_session(
            db=db,
            user_id=current_user.id,
            request=request,
        )
        return SessionResponse.from_orm(session)
    except SessionServiceError as e:
        log_exception(logger, f"Session service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in create_session: {str(e)}", sys.exc_info()
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to create session: {str(e)}"
        )


@router.get("/agent/sessions", response_model=SessionListResponse)
async def get_sessions(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    size: int = Query(20, ge=1, le=100, description="Number of sessions per page"),
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> SessionListResponse:
    """
    Get user's chat sessions with pagination
    """
    try:
        offset = (page - 1) * size
        sessions, total = await session_service.get_user_sessions_with_total(
            db=db,
            user_id=current_user.id,
            limit=size,
            offset=offset,
        )
        items = [SessionResponse.from_orm(session) for session in sessions]
        pages = (total + size - 1) // size if size else 0
        return SessionListResponse(
            items=items,
            pagination={
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            meta={},
        )
    except SessionServiceError as e:
        log_exception(logger, f"Session service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in get_sessions: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")


@router.get("/agent/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> SessionResponse:
    """
    Get a specific chat session
    """
    try:
        session = await session_service.get_session(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionResponse.from_orm(session)
    except SessionServiceError as e:
        log_exception(logger, f"Session service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in get_session: {str(e)}", sys.exc_info()
        )
        raise HTTPException(status_code=500, detail=f"Failed to get session: {str(e)}")


@router.put("/agent/sessions/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: UUID,
    request: UpdateSessionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> SessionResponse:
    """
    Update a chat session
    """
    try:
        session = await session_service.update_session(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
            request=request,
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return SessionResponse.from_orm(session)
    except SessionServiceError as e:
        log_exception(logger, f"Session service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in update_session: {str(e)}", sys.exc_info()
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to update session: {str(e)}"
        )


@router.delete("/agent/sessions/{session_id}")
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> Dict[str, str]:
    """
    Delete a chat session
    """
    try:
        deleted = await session_service.delete_session(
            db=db,
            session_id=session_id,
            user_id=current_user.id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"message": "Session deleted successfully"}
    except SessionServiceError as e:
        log_exception(logger, f"Session service error: {str(e)}", sys.exc_info())
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        log_exception(
            logger, f"Unexpected error in delete_session: {str(e)}", sys.exc_info()
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to delete session: {str(e)}"
        )


def _build_quota_error_payload(error: DailyTokenQuotaExceededError) -> Dict[str, Any]:
    return {
        "message": str(error),
        "limit": error.limit,
        "used": error.used,
        "reset_at": error.reset_at.isoformat(),
    }
