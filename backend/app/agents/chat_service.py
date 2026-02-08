"""
Chat Service Layer

This module contains business logic for chat operations.
It orchestrates the chat workflow by coordinating between:
- Agent Service (AI response generation)
- Message Handler (data persistence)
- Session Management (conversation tracking)

"""

import asyncio
import inspect
import sys
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import ROOT_AGENT_NAME
from app.agents.agent_service import AgentServiceError, AgentStreamEvent, agent_service
from app.agents.service_types import AgentServiceResult, LlmInvocationOverrides
from app.agents.services.streaming import stream_with_heartbeat
from app.agents.session_overview_service import (
    OverviewUpdateResult,
    session_overview_service,
)
from app.cardbox.service import cardbox_service
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.db.models.user import User
from app.handlers import agent_message as agent_message_service
from app.handlers import agent_session as session_handler
from app.handlers.agent_message import AgentMessageCreationError
from app.handlers.agent_session import SessionHandlerError
from app.schemas.agent_message import (
    AgentMessageResponse,
    SendMessageResponse,
    TokenUsageSummary,
)
from app.services.token_quota_service import (
    DailyTokenQuotaExceededError,
    DailyUsageHandle,
    TokenSource,
    begin_daily_usage,
    finalize_daily_usage,
)
from app.services.user_llm_credentials import (
    ResolvedLlmCredential,
    user_llm_credential_service,
)

logger = get_logger(__name__)


_COST_QUANTIZE = Decimal("0.000001")

T = TypeVar("T")


class ChatServiceError(Exception):
    """Base exception for chat service errors."""


class ChatService:
    """
    Service class for orchestrating chat operations.

    This service coordinates the chat workflow but delegates AI generation
    to the existing AgentService. It focuses on:
    - Message lifecycle management
    - Session coordination
    - Database transaction orchestration
    - Business workflow coordination
    """

    def __init__(self) -> Any:
        # Delegate AI operations to existing AgentService
        self.agent_service = agent_service

    def _require_session(self, db: AsyncSession) -> AsyncSession:
        """Ensure ChatService receives a real AsyncSession."""

        if not isinstance(db, AsyncSession):
            raise ChatServiceError(
                "ChatService requires an AsyncSession; use the get_async_db dependency."
            )
        return db

    async def _ensure_session(
        self,
        db: AsyncSession,
        user_id: UUID,
        session_id: Optional[UUID] = None,
        name: Optional[str] = None,
        agent_name: str = ROOT_AGENT_NAME,
    ):
        """Fetch existing session or create a new one for the user."""
        try:
            return await session_handler.ensure_session(
                db,
                user_id=user_id,
                session_id=session_id,
                name=name,
                agent_name=agent_name,
            )
        except SessionHandlerError as e:
            raise ChatServiceError(f"Session management error: {str(e)}")

    @staticmethod
    def _format_cost(value: Optional[Decimal]) -> Optional[str]:
        if value is None:
            return None
        try:
            return str(value.quantize(_COST_QUANTIZE))
        except Exception:
            return str(value)

    def _make_usage_summary(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_usd: Optional[Decimal],
        token_source: Optional[str] = None,
    ) -> TokenUsageSummary:
        return TokenUsageSummary(
            prompt_tokens=max(int(prompt_tokens), 0),
            completion_tokens=max(int(completion_tokens), 0),
            total_tokens=max(int(total_tokens), 0),
            cost_usd=self._format_cost(cost_usd),
            token_source=token_source,
        )

    def _apply_session_usage(
        self,
        session: AgentSession,
        prompt_delta: int,
        completion_delta: int,
        total_delta: int,
        cost_delta: Optional[Decimal],
    ) -> TokenUsageSummary:
        session.prompt_tokens_total = max(
            int(getattr(session, "prompt_tokens_total", 0) or 0) + int(prompt_delta),
            0,
        )
        session.completion_tokens_total = max(
            int(getattr(session, "completion_tokens_total", 0) or 0)
            + int(completion_delta),
            0,
        )
        session.total_tokens_total = max(
            int(getattr(session, "total_tokens_total", 0) or 0) + int(total_delta),
            0,
        )

        raw_cost = getattr(session, "cost_usd_total", None)
        if raw_cost is None:
            current_cost = Decimal("0")
        else:
            current_cost = Decimal(str(raw_cost))

        if cost_delta is not None:
            current_cost += cost_delta

        session.cost_usd_total = current_cost

        return self._make_usage_summary(
            session.prompt_tokens_total,
            session.completion_tokens_total,
            session.total_tokens_total,
            current_cost,
        )

    async def _resolve_agent_result(self, candidate: Any) -> Any:
        """Normalize AgentService outputs to a final result object."""

        if hasattr(candidate, "__aiter__"):
            return await self._consume_agent_stream(candidate)  # async iterator

        if inspect.isawaitable(candidate):
            return await candidate

        return candidate

    async def _consume_agent_stream(
        self, stream: AsyncIterator[AgentStreamEvent]
    ) -> AgentServiceResult:
        """Drain an AgentService event stream until the final result."""

        async for stream_event in stream:
            if isinstance(stream_event, AgentStreamEvent):
                event_name = stream_event.event
                payload = stream_event.data
            elif isinstance(stream_event, dict):
                event_name = stream_event.get("event")
                payload = stream_event.get("data")
            else:
                event_name = getattr(stream_event, "event", None)
                payload = getattr(stream_event, "data", None)

            if event_name == "final":
                return self._agent_result_from_payload(payload or {})

            if event_name == "error":
                message = (payload or {}).get("message") or "Agent stream failed"
                raise ChatServiceError(message)

        raise ChatServiceError("Agent stream ended without a final response")

    @staticmethod
    def _coerce_int(value: Any, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_optional_int(value: Any) -> Optional[int]:
        try:
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    def _agent_result_from_payload(self, payload: Dict[str, Any]) -> AgentServiceResult:
        cost_value = payload.get("cost_usd")
        cost_decimal: Optional[Decimal]
        if cost_value in (None, ""):
            cost_decimal = None
        else:
            try:
                cost_decimal = Decimal(str(cost_value))
            except Exception:
                cost_decimal = None

        return AgentServiceResult(
            content=(payload.get("content") or ""),
            prompt_tokens=self._coerce_int(payload.get("prompt_tokens")),
            completion_tokens=self._coerce_int(payload.get("completion_tokens")),
            total_tokens=self._coerce_int(payload.get("total_tokens")),
            cost_usd=cost_decimal,
            response_time_ms=self._coerce_optional_int(payload.get("response_time_ms")),
            model_name=payload.get("model_name"),
            raw_response=payload,
            context_token_usage=payload.get("context_token_usage"),
            context_budget_tokens=self._coerce_optional_int(
                payload.get("context_budget_tokens")
            ),
            context_window_tokens=self._coerce_optional_int(
                payload.get("context_window_tokens")
            ),
            context_messages_selected=self._coerce_optional_int(
                payload.get("context_messages_selected")
            ),
            context_messages_dropped=self._coerce_optional_int(
                payload.get("context_messages_dropped")
            ),
            context_box_messages_selected=self._coerce_optional_int(
                payload.get("context_box_messages_selected")
            ),
            context_box_messages_dropped=self._coerce_optional_int(
                payload.get("context_box_messages_dropped")
            ),
            tool_runs=list(payload.get("tool_runs") or []),
        )

    async def _resolve_llm_context(
        self, db: AsyncSession, user_id: UUID
    ) -> Tuple[
        TokenSource, Optional[LlmInvocationOverrides], Optional[ResolvedLlmCredential]
    ]:
        credential = await user_llm_credential_service.resolve_active_credential(
            db, user_id=user_id
        )
        if credential is None:
            return "system", None, None

        overrides = LlmInvocationOverrides(
            token_source="user",
            provider=credential.provider,
            api_key=credential.api_key,
            api_base=credential.api_base,
            model_override=credential.model_override,
        )
        return "user", overrides, credential

    async def send_message(
        self,
        db: AsyncSession,
        user: User,
        content: str,
        session_id: Optional[UUID] = None,
        agent_name: str = ROOT_AGENT_NAME,
    ) -> SendMessageResponse:
        """
        Orchestrate the complete chat workflow.

        This method coordinates the chat process by:
        1. Managing message lifecycle (create user message, prepare agent message)
        2. Delegating AI response generation to AgentService
        3. Coordinating database transactions
        4. Managing session tracking

        Args:
            db: Database session
            user: Current user
            content: Message content from user

        Returns:
            SendMessageResponse with both user and agent messages

        Raises:
            ChatServiceError: If any step in the workflow fails
        """
        db = self._require_session(db)
        user_id = user.id
        token_source, llm_overrides, _ = await self._resolve_llm_context(db, user_id)
        usage_handle: Optional[DailyUsageHandle] = await begin_daily_usage(
            db, user=user, token_source=token_source
        )

        async def _record_usage(tokens_value: int) -> None:
            try:
                await finalize_daily_usage(
                    db,
                    handle=usage_handle,
                    tokens_delta=int(tokens_value or 0),
                    max_tokens_snapshot=settings.litellm_completion_max_tokens,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to record daily token usage user=%s err=%s",
                    user_id,
                    exc,
                    exc_info=True,
                )

        try:
            # 1. Ensure session exists for this conversation
            session = await self._ensure_session(
                db,
                user_id=user_id,
                session_id=session_id,
                agent_name=agent_name,
            )
            session_id = session.id

            # 2. Create user message
            user_message = await agent_message_service.create_agent_message(
                db,
                user_id=user_id,
                content=content,
                sender="user",
                session_id=session_id,
                session=session,
                metadata={"source": "manual"},
            )
            user_message_id = str(user_message.id)
            logger.info(f"Created user message: {user_message_id}")

            # 3. Create empty agent message for token tracking
            agent_message = await agent_message_service.create_agent_message(
                db,
                user_id=user_id,
                content="",
                sender="agent",
                session_id=session_id,
                session=session,
                sync_to_cardbox=False,
                metadata={"source": "manual"},
            )
            agent_message_id = agent_message.id
            logger.info(f"Created agent message: {agent_message_id}")

            # 5. Delegate AI response generation to AgentService
            # This is where we use the existing agent_service instead of duplicating logic
            agent_result = await self._resolve_agent_result(
                self.agent_service.generate_response_with_tools(
                    content,
                    db,
                    user_id=user_id,
                    message_id=agent_message_id,  # For token tracking
                    session_id=session_id,
                    agent_name=agent_name,
                    llm_overrides=llm_overrides,
                )
            )

            # 6. Update agent message with the actual response content
            updated_agent_message = await agent_message_service.update_agent_message(
                db,
                message=agent_message,
                content=agent_result.content,
                prompt_tokens=agent_result.prompt_tokens,
                completion_tokens=agent_result.completion_tokens,
                total_tokens=agent_result.total_tokens,
                cost_usd=agent_result.cost_usd,
                response_time_ms=agent_result.response_time_ms,
                model_name=agent_result.model_name,
            )

            logger.info(
                f"Updated agent message content: {agent_message_id}, result: {updated_agent_message is not None}"
            )

            if updated_agent_message is None:
                raise ChatServiceError(
                    f"Failed to update agent message content: {agent_message_id}"
                )

            prompt_delta = int(agent_result.prompt_tokens or 0)
            completion_delta = int(agent_result.completion_tokens or 0)
            total_delta = int(agent_result.total_tokens or 0)
            cost_delta = agent_result.cost_usd

            usage_delta_summary = self._make_usage_summary(
                prompt_delta,
                completion_delta,
                total_delta,
                cost_delta,
                token_source=token_source,
            )
            usage_total_summary = self._apply_session_usage(
                session,
                prompt_delta,
                completion_delta,
                total_delta,
                cost_delta,
            )

            await _record_usage(total_delta)

            cardbox_service.sync_message(updated_agent_message, session=session)

            session.touch()

            # 8. Commit all changes
            await agent_message_service.commit_agent_messages(db)
            logger.info("Committed all changes to database")

            # 9. Start background overview update (non-blocking)
            asyncio.create_task(self._update_overview_background(db, session, user_id))

            # 10. Return response with fresh objects converted to Pydantic models
            return SendMessageResponse(
                message=AgentMessageResponse.from_orm(user_message),
                agent_response=AgentMessageResponse.from_orm(updated_agent_message),
                session_id=session_id,
                usage_delta=usage_delta_summary,
                usage_total=usage_total_summary,
                context_token_usage=agent_result.context_token_usage,
                context_window_tokens=agent_result.context_window_tokens,
                context_budget_tokens=agent_result.context_budget_tokens,
                context_messages_selected=agent_result.context_messages_selected,
                context_messages_dropped=agent_result.context_messages_dropped,
                context_box_messages_selected=agent_result.context_box_messages_selected,
                context_box_messages_dropped=agent_result.context_box_messages_dropped,
                tool_runs=agent_result.tool_runs,
            )

        except DailyTokenQuotaExceededError:
            raise
        except AgentMessageCreationError as e:
            await db.rollback()
            log_exception(
                logger, f"Agent message creation error: {str(e)}", sys.exc_info()
            )
            raise ChatServiceError(f"Failed to create agent message: {str(e)}")
        except Exception as e:
            await db.rollback()
            log_exception(
                logger, f"Unexpected error in send_message: {str(e)}", sys.exc_info()
            )
            raise ChatServiceError(f"Failed to send message: {str(e)}")

    async def stream_message(
        self,
        db: AsyncSession,
        user: User,
        content: str,
        session_id: Optional[UUID] = None,
        agent_name: str = ROOT_AGENT_NAME,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream agent responses over SSE while persisting chat state."""
        logger.info(f"ChatService.stream_message called with session_id: {session_id}")

        db = self._require_session(db)
        user_id = user.id
        token_source, llm_overrides, _ = await self._resolve_llm_context(db, user_id)
        usage_handle: Optional[DailyUsageHandle] = await begin_daily_usage(
            db, user=user, token_source=token_source
        )

        async def _record_usage(tokens_value: int) -> None:
            try:
                await finalize_daily_usage(
                    db,
                    handle=usage_handle,
                    tokens_delta=int(tokens_value or 0),
                    max_tokens_snapshot=settings.litellm_completion_max_tokens,
                )
            except Exception as exc:  # pragma: no cover - defensive logging
                logger.warning(
                    "Failed to record daily token usage user=%s err=%s",
                    user_id,
                    exc,
                    exc_info=True,
                )

        try:
            session = await self._ensure_session(
                db,
                user_id=user_id,
                session_id=session_id,
                agent_name=agent_name,
            )
            session_id = session.id
            logger.info(f"After ensure_session, using session_id: {session_id}")

            user_message = await agent_message_service.create_agent_message(
                db,
                user_id=user_id,
                content=content,
                sender="user",
                session_id=session_id,
                session=session,
                metadata={"source": "manual"},
            )

            agent_message = await agent_message_service.create_agent_message(
                db,
                user_id=user_id,
                content="",
                sender="agent",
                session_id=session_id,
                session=session,
                is_typing=True,
                sync_to_cardbox=False,
                metadata={"source": "manual"},
            )

            user_payload = AgentMessageResponse.from_orm(user_message).model_dump(
                mode="json"
            )
            agent_payload = AgentMessageResponse.from_orm(agent_message).model_dump(
                mode="json"
            )

        except DailyTokenQuotaExceededError:
            raise
        except AgentMessageCreationError as exc:
            await db.rollback()
            log_exception(
                logger, f"Agent message creation error: {str(exc)}", sys.exc_info()
            )
            raise ChatServiceError(f"Failed to create agent message: {str(exc)}")

        async def iterator() -> AsyncIterator[Dict[str, Any]]:
            assistant_fragments: List[str] = []

            # Send initial events so the UI can reconcile optimistic entries
            yield {"event": "message", "data": user_payload}
            yield {
                "event": "agent_message",
                "data": {**agent_payload, "is_typing": True},
            }

            agent_event_stream = self.agent_service.stream_response_with_tools(
                content,
                db,
                user_id=user_id,
                message_id=agent_message.id,
                session_id=session_id,
                agent_name=agent_name,
                llm_overrides=llm_overrides,
            )

            heartbeat_context = {
                "session_id": str(session_id),
                "agent_name": agent_name,
                "message_id": str(agent_message.id),
            }

            try:
                async for stream_event in stream_with_heartbeat(
                    agent_event_stream,
                    interval=settings.agent_stream_heartbeat_interval,
                    context=heartbeat_context,
                ):
                    name = (
                        stream_event.event
                        if isinstance(stream_event, AgentStreamEvent)
                        else stream_event.get("event")  # type: ignore[attr-defined]
                    )
                    payload = (
                        stream_event.data
                        if isinstance(stream_event, AgentStreamEvent)
                        else stream_event.get("data")  # type: ignore[attr-defined]
                    )

                    if name == "delta":
                        text = (payload or {}).get("content", "") or ""
                        assistant_fragments.append(text)
                        yield {
                            "event": "delta",
                            "data": {"id": str(agent_message.id), "content": text},
                        }
                    elif name == "final":
                        final_payload = payload or {}
                        combined_content = final_payload.get(
                            "content", "".join(assistant_fragments)
                        )

                        cost_value = final_payload.get("cost_usd")
                        if cost_value is not None:
                            try:
                                cost_value = Decimal(str(cost_value))
                            except Exception:  # pragma: no cover - defensive
                                cost_value = None

                        try:
                            updated_agent = (
                                await agent_message_service.update_agent_message(
                                    db,
                                    message=agent_message,
                                    content=combined_content,
                                    prompt_tokens=final_payload.get("prompt_tokens"),
                                    completion_tokens=final_payload.get(
                                        "completion_tokens"
                                    ),
                                    total_tokens=final_payload.get("total_tokens"),
                                    cost_usd=cost_value,
                                    response_time_ms=final_payload.get(
                                        "response_time_ms"
                                    ),
                                    model_name=final_payload.get("model_name"),
                                    is_typing=False,
                                )
                            )

                            if updated_agent is None:
                                raise ChatServiceError(
                                    "Failed to persist streamed agent message"
                                )

                            prompt_delta = int(final_payload.get("prompt_tokens") or 0)
                            completion_delta = int(
                                final_payload.get("completion_tokens") or 0
                            )
                            total_delta = int(final_payload.get("total_tokens") or 0)

                            usage_delta_summary = self._make_usage_summary(
                                prompt_delta,
                                completion_delta,
                                total_delta,
                                cost_value,
                                token_source=token_source,
                            )
                            usage_total_summary = self._apply_session_usage(
                                session,
                                prompt_delta,
                                completion_delta,
                                total_delta,
                                cost_value,
                            )
                            await _record_usage(total_delta)

                            final_payload["cost_usd"] = usage_delta_summary.cost_usd
                            final_payload[
                                "usage_delta"
                            ] = usage_delta_summary.model_dump()
                            final_payload[
                                "usage_total"
                            ] = usage_total_summary.model_dump()

                            session.touch()
                            await agent_message_service.commit_agent_messages(db)
                            cardbox_service.sync_message(updated_agent, session=session)

                        except Exception as exc:  # pragma: no cover - defensive
                            await db.rollback()
                            log_exception(
                                logger,
                                f"Error updating agent message after stream: {exc}",
                                sys.exc_info(),
                            )
                            raise ChatServiceError(
                                f"Failed to finalize streamed message: {str(exc)}"
                            ) from exc

                        persisted_agent = AgentMessageResponse.from_orm(
                            agent_message
                        ).model_dump(mode="json")

                        yield {
                            "event": "final",
                            "data": {
                                "message": persisted_agent,
                                "metrics": final_payload,
                            },
                        }

                        overview_update = await self._update_overview_background(
                            db, session, user_id
                        )
                        if overview_update:
                            # Signal to the client that the session overview has finished updating
                            yield {
                                "event": "session_overview",
                                "data": {
                                    "session_id": str(session.id),
                                    "title": overview_update.overview.title,
                                    "summary": overview_update.overview.description,
                                    "confidence": overview_update.overview.confidence,
                                    "model_name": overview_update.overview.model_name,
                                    "applied": overview_update.applied_to_session,
                                },
                            }
                        break
                    else:
                        yield {"event": name, "data": payload}

            except AgentServiceError as exc:
                await db.rollback()
                logger.error(f"AgentService error in stream_message: {str(exc)}")
                log_exception(
                    logger, "ChatService AgentServiceError details", sys.exc_info()
                )
                raise ChatServiceError(str(exc)) from exc
            except Exception as exc:  # pragma: no cover - defensive logging
                await db.rollback()
                logger.error(f"Unexpected error in stream_message: {str(exc)}")
                log_exception(
                    logger,
                    "ChatService unexpected error details",
                    sys.exc_info(),
                )
                raise ChatServiceError(f"Failed to stream message: {str(exc)}") from exc

        return iterator()

    async def get_chat_history(
        self,
        db: AsyncSession,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        session_id: Optional[UUID] = None,
    ) -> Tuple[List[AgentMessageResponse], int]:
        """
        Get chat history for a user using AsyncSession.
        """
        try:
            total_count = await agent_message_service.count_agent_messages(
                db, user_id=user_id, session_id=session_id
            )
            messages: List[AgentMessage] = []
            if offset < total_count and limit > 0:
                remaining = total_count - offset
                fetch = min(limit, remaining)
                if fetch > 0:
                    start_offset = max(total_count - offset - fetch, 0)
                    messages = await agent_message_service.list_agent_messages(
                        db,
                        user_id=user_id,
                        limit=fetch,
                        offset=start_offset,
                        session_id=session_id,
                    )

            responses = [AgentMessageResponse.from_orm(msg) for msg in messages]
            return responses, total_count
        except Exception as exc:
            log_exception(
                logger, f"Error in get_chat_history: {str(exc)}", sys.exc_info()
            )
            raise ChatServiceError(f"Failed to get chat history: {str(exc)}") from exc

    async def clear_chat_history(self, db: AsyncSession, user_id: UUID) -> int:
        """Clear all chat history for a user asynchronously."""
        try:
            deleted_count = await agent_message_service.delete_agent_messages(
                db, user_id=user_id
            )
            await session_handler.soft_delete_sessions_for_user(db, user_id=user_id)
            await agent_message_service.commit_agent_messages(db)
            return deleted_count
        except Exception as exc:
            await db.rollback()
            log_exception(
                logger, f"Error in clear_chat_history: {str(exc)}", sys.exc_info()
            )
            raise ChatServiceError(f"Failed to clear chat history: {str(exc)}") from exc

    async def clear_session_history(
        self, db: AsyncSession, user_id: UUID, session_id: UUID
    ) -> int:
        """Clear chat history for a specific session asynchronously."""
        try:
            deleted_count = (
                await agent_message_service.delete_agent_messages_by_session(
                    db, user_id=user_id, session_id=session_id
                )
            )
            await agent_message_service.commit_agent_messages(db)
            return deleted_count
        except Exception as exc:
            await db.rollback()
            log_exception(
                logger, f"Error in clear_session_history: {str(exc)}", sys.exc_info()
            )
            raise ChatServiceError(
                f"Failed to clear session history: {str(exc)}"
            ) from exc

    async def _update_overview_background(
        self, db: AsyncSession, session: AgentSession, user_id: UUID
    ) -> Optional[OverviewUpdateResult]:
        """
        Background task to update session overview without blocking user interaction.

        This method runs asynchronously to update the session title and summary
        without blocking the streaming response or user input.

        Args:
            db: Database session
            session: Agent session to update
            user_id: ID of the user
        """
        result: Optional[OverviewUpdateResult] = None
        try:
            logger.info(f"Starting background overview update for session {session.id}")
            result = await session_overview_service.maybe_update_overview(
                db=db,
                session=session,
                user_id=user_id,
            )
            if result is None:
                logger.info(
                    f"Background overview update completed for session {session.id}: no changes"
                )
            else:
                logger.info(
                    "Background overview update completed for session %s (applied=%s)",
                    session.id,
                    result.applied_to_session,
                )
            return result
        except Exception as e:
            logger.error(
                f"Background overview update failed for session {session.id}: {str(e)}"
            )
            # Don't re-raise - this is a background operation that shouldn't affect the main flow
            return None


# Create singleton instance
chat_service = ChatService()
