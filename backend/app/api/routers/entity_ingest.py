"""Endpoint for free-text entity ingestion via agent tools."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import ENTITY_INGEST_AGENT_NAME
from app.agents.agent_service import agent_service
from app.agents.chat_service import chat_service
from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.agent_session import AgentSession
from app.handlers import agent_session as session_handler
from app.schemas.entity_ingest import EntityIngestRequest, EntityIngestResponse

router = StrictAPIRouter()


@router.post("/entity/ingest", response_model=EntityIngestResponse)
async def ingest_entities(
    request: EntityIngestRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user=Depends(get_current_user),
) -> EntityIngestResponse:
    """Use the dedicated ingest agent to convert free text into entities via tools."""

    async def _ensure_session() -> AgentSession:
        if request.session_id:
            session = await session_handler.get_session(
                db,
                session_id=request.session_id,
                user_id=current_user.id,
            )
            if session is None:
                session = await session_handler.create_session_with_id(
                    db,
                    user_id=current_user.id,
                    session_id=request.session_id,
                    name="Entity Ingest Session",
                    session_type=AgentSession.TYPE_SYSTEM,
                )
        else:
            session = await session_handler.create_session(
                db,
                user_id=current_user.id,
                name="Entity Ingest Session",
                session_type=AgentSession.TYPE_SYSTEM,
            )
        return session

    # 确保存在可用的会话记录，以便后续审计日志外键约束不失败。
    try:
        session = await _ensure_session()
        session_id = session.id
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare ingest session: {exc}",
        )

    # generate_response_with_tools 可能返回异步流；复用 ChatService 解析逻辑。
    result = await chat_service._resolve_agent_result(
        agent_service.generate_response_with_tools(
            user_message=request.text,
            db=db,
            user_id=current_user.id,
            conversation_history=None,
            message_id=None,
            session_id=session_id,
            agent_name=ENTITY_INGEST_AGENT_NAME,
        )
    )

    return EntityIngestResponse(
        content=result.content,
        tool_runs=result.tool_runs or [],
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.total_tokens,
        cost_usd=result.cost_usd,
        model_name=result.model_name,
    )
