"""
Agent Service

This service handles AI agent interactions using LiteLLM for chat completion.
It provides a centralized way to manage agent conversations and can be easily
extended to support additional AI features in the future.
"""

import asyncio
import json
import sys
import time
from collections import defaultdict
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_registry import (
    NOTE_AGENT_NAME,
    ROOT_AGENT_NAME,
    AgentProfile,
    agent_registry,
)
from app.agents.context_builder import ContextBuildResult, context_builder
from app.agents.conversation_compressor import conversation_compressor
from app.agents.conversation_history import ConversationMessage
from app.agents.llm import llm_client
from app.agents.registry import ToolAccessRegistry
from app.agents.service_types import (
    AgentRuntimeContext,
    AgentServiceResult,
    AgentStreamEvent,
    LlmInvocationOverrides,
)
from app.agents.services import ContextPipeline, PromptingService, ToolExecutionEngine
from app.agents.services.streaming import (
    StreamingContextSnapshot,
    StreamingManager,
    litellm_call_context,
    serialize_agent_result,
)
from app.agents.token_tracker import TokenUsage, token_tracker
from app.agents.tool_policy import tool_policy
from app.agents.tools.planner import PreparedToolCall, ToolExecutionPlanner
from app.cardbox.utils import tenant_for_user
from app.core.config import settings
from app.core.logging import get_logger, log_exception
from app.handlers import user_preferences as user_preferences_service
from app.services.note_reference_service import note_reference_service
from app.utils.debug_utils import debug_manager
from app.utils.timezone_util import resolve_timezone, utc_now

logger = get_logger(__name__)

MAX_TOOL_EXECUTION_ROUNDS = 6


class AgentServiceError(Exception):
    """Exception raised for errors in the AgentService"""


class AgentService:
    """Service for handling AI agent interactions using LiteLLM"""

    def __init__(self) -> None:
        """Initialize the agent service with LiteLLM configuration"""
        self.llm = llm_client
        self.model = llm_client.default_model
        self.api_key = llm_client.default_api_key
        self.base_url = llm_client.default_api_base
        self.temperature = settings.litellm_temperature
        self.max_tokens = settings.litellm_completion_max_tokens
        self.context_window_tokens = settings.litellm_context_window_tokens
        self.timeout = settings.litellm_timeout
        self.token_tracker = token_tracker
        self.tool_policy = tool_policy
        self.conversation_compressor = conversation_compressor
        self.context_builder = context_builder
        self.context_pipeline = ContextPipeline()
        self.prompting_service = PromptingService()
        self.tool_executor = ToolExecutionEngine(tool_policy=tool_policy)
        self.streaming_manager = StreamingManager(
            llm_client=self.llm,
            token_tracker=self.token_tracker,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            error_cls=AgentServiceError,
            sanitize_tool_runs=self.tool_executor.sanitize_tool_runs,
        )
        self.max_tool_rounds = getattr(
            settings, "agent_max_tool_rounds", MAX_TOOL_EXECUTION_ROUNDS
        )

        # Enable LiteLLM debug mode if configured
        if debug_manager.is_litellm_debug_enabled():
            debug_manager.enable_litellm_debug()
            debug_manager.log_litellm_config(
                self.model,
                self.api_key,
                self.base_url,
                self.temperature,
                self.max_tokens,
                self.context_window_tokens,
            )

    async def generate_response_with_tools(
        self,
        user_message: str,
        db: AsyncSession,
        user_id: UUID,
        conversation_history: Optional[List[ConversationMessage]] = None,
        message_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        agent_name: str = ROOT_AGENT_NAME,
        llm_overrides: Optional[LlmInvocationOverrides] = None,
    ) -> AgentServiceResult:
        """
        Generate an AI agent response with tool calling capabilities using LiteLLM

        Args:
            user_message: The user's input message
            db: Database session
            user_id: ID of the user
            conversation_history: Optional list of previous messages for context

        Returns:
            AgentServiceResult containing the final response content and usage metrics
        """
        agent_profile: AgentProfile = agent_registry.get_profile(agent_name)
        start_time = time.time()
        log_context = {
            "action": "agent.generate.start",
            "user_id": str(user_id),
            "session_id": str(session_id) if session_id else None,
            "message_id": str(message_id) if message_id else None,
            "agent_name": agent_name,
        }
        runtime = AgentRuntimeContext(
            db=db,
            user_id=user_id,
            agent_name=agent_name,
            session_id=session_id,
            message_id=message_id,
            log_context=log_context,
        )
        logger.info(
            f"Generating response with tools: {user_message[:20]}...",
            extra=log_context,
        )
        try:
            # Get tool registry
            tool_registry = ToolAccessRegistry(
                db=db,
                user_id=user_id,
                agent_name=agent_name,
            )
            tools = tool_registry.get_all_tool_definitions()

            # Resolve user language preference
            language = await self.prompting_service.get_user_language(db, user_id)

            history_source = "provided"
            if not conversation_history:
                (
                    conversation_history,
                    history_source,
                ) = await self.context_pipeline.get_conversation_history(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    limit=25,
                )

            context_summaries: List[Dict[str, Any]] = []
            (
                context_messages,
                loaded_context_summaries,
            ) = await self.context_pipeline.load_session_context_messages(
                db,
                user_id=user_id,
                session_id=session_id,
            )
            if context_messages:
                if conversation_history:
                    conversation_history = list(conversation_history) + context_messages
                else:
                    conversation_history = context_messages
                context_summaries = loaded_context_summaries

            logger.info(
                "Prepared conversation context",
                extra={
                    **log_context,
                    "action": "agent.history.ready",
                    "history_source": history_source,
                    "history_count": len(conversation_history or []),
                },
            )

            context_result = self._prepare_conversation_context(
                user_id=user_id,
                user_message=user_message,
                conversation_history=conversation_history,
                language=language,
                agent_profile=agent_profile,
                datetime_directive=await self._resolve_datetime_directive(db, user_id),
            )
            messages = list(context_result.messages)

            note_reference_lookup = None
            if agent_name == NOTE_AGENT_NAME:
                reference_data = await note_reference_service.get_reference_data(
                    db, user_id, session_id
                )
                if any(
                    (
                        reference_data.tags,
                        reference_data.tasks,
                        reference_data.persons,
                    )
                ):
                    note_reference_lookup = note_reference_service.build_lookup(
                        reference_data
                    )
                    metadata_message = note_reference_service.build_prompt_message(
                        reference_data
                    )
                    messages = self.prompting_service.inject_auxiliary_system_message(
                        messages, metadata_message
                    )
                else:
                    note_reference_lookup = note_reference_service.build_lookup(
                        reference_data
                    )
            else:
                note_reference_lookup = None

            context_usage_snapshot = context_result.token_usage or {}
            context_messages_selected = len(context_result.selected_history)
            context_messages_dropped = len(context_result.dropped_history)
            context_box_messages_selected = sum(
                1
                for msg in context_result.selected_history
                if getattr(msg, "source", None) == "context_box"
            )
            context_box_messages_dropped = sum(
                1
                for msg in context_result.dropped_history
                if getattr(msg, "source", None) == "context_box"
            )

            self.context_pipeline.log_context_truncation(
                user_id=user_id,
                session_id=session_id,
                context_result=context_result,
            )

            debug_manager.log_context_token_usage(context_result.token_usage)

            tool_runs = []
            context_snapshot = StreamingContextSnapshot(
                context_token_usage=context_usage_snapshot,
                context_messages_selected=context_messages_selected,
                context_messages_dropped=context_messages_dropped,
                context_box_messages_selected=context_box_messages_selected,
                context_box_messages_dropped=context_box_messages_dropped,
                context_budget_tokens=settings.conversation_context_budget,
                context_window_tokens=self.context_window_tokens,
                tool_runs=tool_runs,
            )

            # Use provided session_id or generate new one
            session_was_provided = session_id is not None
            incoming_session_id = session_id
            logger.info(
                "Session identifier received",
                extra={**log_context, "action": "agent.session.input"},
            )
            if not session_id:
                session_id = uuid4()
                logger.info(
                    "Generated new session identifier",
                    extra={
                        **log_context,
                        "action": "agent.session.generated",
                        "session_id": str(session_id),
                    },
                )
                runtime.set_session_id(session_id)

            cardbox_session = await self.tool_executor.resolve_session_for_cardbox(
                db,
                session_id_value=incoming_session_id,
                user_id=user_id,
                session_was_provided=session_was_provided,
            )
            runtime.set_cardbox_session(cardbox_session)
            logger.info(
                "Resolved Cardbox session",
                extra={
                    **log_context,
                    "action": "agent.cardbox.session",
                    "cardbox_box": getattr(cardbox_session, "cardbox_name", None),
                },
            )

            if context_summaries:
                tenant_id = tenant_for_user(user_id)
                self.context_pipeline.append_context_usage_log(
                    session=cardbox_session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    summaries=context_summaries,
                )

            if (
                context_result.summary_candidates
                and cardbox_session is not None
                and session_id is not None
            ):
                summary_result = await self.conversation_compressor.compress(
                    session=cardbox_session,
                    user_id=user_id,
                    language=language,
                    candidates=context_result.summary_candidates,
                )
                if summary_result:
                    messages.insert(
                        1,
                        {
                            "role": summary_result.message.role,
                            "content": summary_result.message.content,
                        },
                    )
                    logger.info(
                        "Inserted conversation summary into context",
                        extra={
                            **log_context,
                            "action": "agent.summary.inserted",
                            "covered_messages": (
                                summary_result.message.metadata.get(
                                    "covered_messages", []
                                )
                                if summary_result.message.metadata
                                else []
                            ),
                            "card_id": summary_result.card_id,
                        },
                    )

            tool_iterations = 0
            loop_iterations = 0

            while True:
                loop_iterations += 1
                iteration_start = time.time()
                logger.info(
                    "Agent response loop iteration %s starting (tool_iterations=%s)",
                    loop_iterations,
                    tool_iterations,
                    extra=log_context,
                )
                params = self._build_litellm_params(
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    metadata={
                        "message_id": message_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "agent_name": agent_name,
                    },
                    llm_overrides=llm_overrides,
                )
                response = await self.llm.completion(
                    messages=params.pop("messages"),
                    metadata=params.pop("metadata", None),
                    **params,
                )
                logger.info(
                    "Agent response loop iteration %s received LLM response in %.2fs",
                    loop_iterations,
                    time.time() - iteration_start,
                    extra=log_context,
                )
                assistant_message = response.choices[0].message
                tool_call_message = self.tool_executor.build_tool_call_message(
                    assistant_message
                )
                logger.info(
                    f"[generate_response_with_tools] Tool call message: {tool_call_message}"
                )
                messages.append(tool_call_message)

                debug_manager.log_litellm_response(
                    response.model,
                    response.usage,
                    (
                        len(assistant_message.tool_calls)
                        if getattr(assistant_message, "tool_calls", None)
                        else 0
                    ),
                )

                tool_calls = getattr(assistant_message, "tool_calls", None) or []
                logger.info(
                    "Agent response loop iteration %s parsed %s tool calls",
                    loop_iterations,
                    len(tool_calls),
                    extra=log_context,
                )
                if not tool_calls:
                    result = self.streaming_manager.attach_context_metadata(
                        self._build_result(response, start_time),
                        context_snapshot,
                    )
                    yield AgentStreamEvent(
                        event="final", data=serialize_agent_result(result)
                    )
                    return

                tool_iterations += 1
                if tool_iterations > self.max_tool_rounds:
                    logger.warning(
                        "Tool call loop exceeded %s rounds",
                        self.max_tool_rounds,
                        extra=log_context,
                    )
                    result = self.streaming_manager.build_fallback_result(
                        content="Tool invocation limit reached. Please adjust your request.",
                        snapshot=context_snapshot,
                    )
                    yield AgentStreamEvent(
                        event="final", data=serialize_agent_result(result)
                    )
                    return

                logger.info(
                    "LLM requested %s tool calls (round %s, loop iteration %s)",
                    len(tool_calls),
                    tool_iterations,
                    loop_iterations,
                )

                tool_counts = defaultdict(int)
                batch_run_id = uuid4()
                tool_failures: List[Dict[str, str]] = []
                ordered_calls_raw = list(self.tool_policy.order_calls(tool_calls))

                tool_sequence = 0
                prepared_calls: List[PreparedToolCall] = []
                for tool_call in ordered_calls_raw:
                    raw_function_name = getattr(tool_call.function, "name", None)
                    function_name = self.tool_executor.normalize_tool_name(
                        raw_function_name
                    )
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    tool_sequence += 1
                    run_record = self.tool_executor.create_tool_run_record(
                        tool_call_id=tool_call.id,
                        tool_name=(
                            function_name
                            if function_name
                            else (
                                str(raw_function_name)
                                if raw_function_name
                                else "invalid_tool"
                            )
                        ),
                        arguments=function_args,
                        sequence=tool_sequence,
                        run_id=batch_run_id,
                    )
                    tool_runs.append(run_record)
                    if not function_name:
                        invalid_event = await self.tool_executor.handle_invalid_tool_call(
                            tool_call=tool_call,
                            run_record=run_record,
                            reason="LLM returned a tool call without a valid function name",
                            error_kind="invalid_tool_call",
                            messages=messages,
                            tool_failures=tool_failures,
                            runtime=runtime,
                        )
                        yield invalid_event
                        continue

                    run_record["tool_name"] = function_name
                    try:
                        metadata = tool_registry.get_tool_metadata(function_name)
                    except ValueError as exc:
                        invalid_event = (
                            await self.tool_executor.handle_invalid_tool_call(
                                tool_call=tool_call,
                                run_record=run_record,
                                reason=str(exc),
                                error_kind="invalid_tool_call",
                                messages=messages,
                                tool_failures=tool_failures,
                                runtime=runtime,
                            )
                        )
                        yield invalid_event
                        continue
                    call_index = tool_counts[function_name] + 1
                    tool_counts[function_name] = call_index
                    prepared_calls.append(
                        PreparedToolCall(
                            tool_call=tool_call,
                            name=function_name,
                            arguments=function_args,
                            run_record=run_record,
                            metadata=metadata,
                            call_index=call_index,
                        )
                    )
                    yield AgentStreamEvent(
                        event="tool_started",
                        data=self.tool_executor.build_tool_event_payload(
                            run_record,
                            include_arguments=True,
                        ),
                    )

                planner = ToolExecutionPlanner()
                execution_plan = planner.plan(prepared_calls)
                tool_execution_start = time.time()

                for batch in execution_plan:
                    batch_events = await self.tool_executor.execute_tool_batch(
                        batch=batch,
                        tool_registry=tool_registry,
                        note_reference_lookup=note_reference_lookup,
                        runtime=runtime,
                        messages=messages,
                        tool_failures=tool_failures,
                    )
                    for event in batch_events:
                        yield event

                tool_execution_time = time.time() - tool_execution_start
                logger.info(
                    "Tool execution round %s completed in %.2fs",
                    tool_iterations,
                    tool_execution_time,
                )

                if tool_failures:
                    failure_message = self.tool_executor.compose_tool_failure_message(
                        tool_failures
                    )
                    logger.warning(
                        "Tool execution encountered failures",
                        extra={
                            **log_context,
                            "action": "agent.tool.failure_summary",
                            "failures": tool_failures,
                        },
                    )
                    result = self.streaming_manager.build_fallback_result(
                        content=failure_message,
                        snapshot=context_snapshot,
                    )
                    yield AgentStreamEvent(
                        event="final", data=serialize_agent_result(result)
                    )
                    return

                # Continue loop so the LLM can inspect the fresh tool outputs
                continue

        except ImportError as e:
            log_exception(logger, f"LiteLLM import error: {e}", sys.exc_info())
            result = self.streaming_manager.build_fallback_result(
                content="LiteLLM not installed, falling back to regular response",
                snapshot=context_snapshot,
            )
            yield AgentStreamEvent(event="final", data=serialize_agent_result(result))
            return
        except Exception as e:
            # Enhanced error logging with debug information
            log_exception(
                logger,
                f"Error in generate_response_with_tools: {str(e)}",
                sys.exc_info(),
            )
            debug_manager.log_error_details(
                user_message,
                str(user_id),
                str(session_id),
                str(message_id),
                self.model,
                self.api_key,
            )
            logger.error(f"  Base URL: {self.base_url}")
            logger.error(f"  Exception Type: {type(e).__name__}")
            logger.error(f"  Exception Details: {str(e)}")
            result = self.streaming_manager.build_fallback_result(
                content=f"Error in tool calling: {str(e)}",
                snapshot=context_snapshot,
            )
            yield AgentStreamEvent(event="final", data=serialize_agent_result(result))
            return

    def _build_litellm_params(
        self,
        *,
        messages: List[Dict[str, Any]],
        metadata: Dict[str, Any],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        stream: bool = False,
        llm_overrides: Optional[LlmInvocationOverrides] = None,
    ) -> Dict[str, Any]:
        """Construct LiteLLM parameter dictionaries with shared configuration."""
        return self.streaming_manager.build_litellm_params(
            messages=messages,
            metadata=metadata,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            overrides=llm_overrides,
        )

    def _build_result(self, response: Any, start_time: float) -> AgentServiceResult:
        """Normalize LiteLLM responses into AgentServiceResult payloads."""

        elapsed_ms: Optional[int] = None
        if start_time:
            elapsed_seconds = max(time.time() - start_time, 0)
            elapsed_ms = int(elapsed_seconds * 1000)

        usage: TokenUsage = self.token_tracker.extract_usage(response)
        cost_usd = self.token_tracker.calculate_cost(response)

        try:
            content = response.choices[0].message.content or ""
        except Exception:
            content = getattr(response, "content", "") or ""

        model_name = getattr(response, "model", None)

        return AgentServiceResult(
            content=content.strip(),
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=cost_usd,
            response_time_ms=elapsed_ms,
            model_name=model_name,
            raw_response=response,
        )

    def _prepare_conversation_context(
        self,
        user_id: UUID,
        user_message: str,
        conversation_history: Optional[List[ConversationMessage]] = None,
        language: str = "en",
        agent_profile: Optional[AgentProfile] = None,
        datetime_directive: Optional[str] = None,
    ) -> ContextBuildResult:
        profile = agent_profile or agent_registry.get_profile(ROOT_AGENT_NAME)
        prompt_bundle = self.prompting_service.build_system_prompt(language, profile)
        system_prompt = prompt_bundle.render()
        if datetime_directive:
            system_prompt = f"{system_prompt}\n\n{datetime_directive}"
        logger.debug(
            "Prepared system prompt",
            extra={
                "agent_name": profile.name,
                "prompt_version": prompt_bundle.version,
                "language_directive": prompt_bundle.language_directive,
            },
        )
        history = conversation_history or []

        result = self.context_builder.build_context(
            user_id=user_id,
            user_message=user_message,
            history=history,
            model=self.model,
            system_prompt=system_prompt,
        )

        return result

    async def _resolve_datetime_directive(
        self, db: Optional[AsyncSession], user_id: UUID
    ) -> Optional[str]:
        if db is None:
            return None
        timezone_value = "UTC"
        try:
            timezone_value = str(
                await user_preferences_service.get_user_timezone(
                    db, user_id=user_id, default="UTC"
                )
                or "UTC"
            )
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug(
                "Falling back to UTC for datetime directive: %s",
                exc,
                exc_info=sys.exc_info(),
            )

        tzinfo = resolve_timezone(timezone_value, default="UTC")
        timezone_label = getattr(tzinfo, "key", timezone_value or "UTC")
        iso_timestamp = utc_now().astimezone(tzinfo).isoformat()
        return (
            "Temporal directive: Current datetime at the user's location is "
            f"{iso_timestamp} (timezone: {timezone_label}). Use this reference "
            "to interpret relative time expressions such as 今天/明天/这个周末."
        )

    async def stream_response_with_tools(
        self,
        user_message: str,
        db: AsyncSession,
        user_id: UUID,
        conversation_history: Optional[List[ConversationMessage]] = None,
        message_id: Optional[UUID] = None,
        session_id: Optional[UUID] = None,
        agent_name: str = ROOT_AGENT_NAME,
        llm_overrides: Optional[LlmInvocationOverrides] = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        """Stream an AI response token-by-token, supporting tool calls."""

        agent_profile: AgentProfile = agent_registry.get_profile(agent_name)
        start_time = time.time()
        stream_log_context = {
            "action": "agent.stream.start",
            "user_id": str(user_id),
            "session_id": str(session_id) if session_id else None,
            "message_id": str(message_id) if message_id else None,
            "agent_name": agent_name,
        }
        runtime = AgentRuntimeContext(
            db=db,
            user_id=user_id,
            agent_name=agent_name,
            session_id=session_id,
            message_id=message_id,
            log_context=stream_log_context,
        )
        logger.info(
            f"Streaming response with tools: {user_message[:20]}...",
            extra=stream_log_context,
        )

        stream_context_usage: Dict[str, int] = {}
        stream_context_messages_selected = 0
        stream_context_messages_dropped = 0
        stream_context_box_selected = 0
        stream_context_box_dropped = 0
        tool_runs: List[Dict[str, Any]] = []
        stream_snapshot: Optional[StreamingContextSnapshot] = None

        try:
            tool_registry = ToolAccessRegistry(
                db=db,
                user_id=user_id,
                agent_name=agent_name,
            )
            tools = tool_registry.get_all_tool_definitions()

            language = await self.prompting_service.get_user_language(db, user_id)
            history_source = "provided"
            if not conversation_history:
                (
                    conversation_history,
                    history_source,
                ) = await self.context_pipeline.get_conversation_history(
                    db,
                    user_id=user_id,
                    session_id=session_id,
                    limit=25,
                )

            context_summaries: List[Dict[str, Any]] = []
            (
                context_messages,
                loaded_context_summaries,
            ) = await self.context_pipeline.load_session_context_messages(
                db,
                user_id=user_id,
                session_id=session_id,
            )
            if context_messages:
                if conversation_history:
                    conversation_history = list(conversation_history) + context_messages
                else:
                    conversation_history = context_messages
                context_summaries = loaded_context_summaries

            logger.info(
                "Prepared streaming conversation context",
                extra={
                    **stream_log_context,
                    "action": "agent.stream.history_ready",
                    "history_source": history_source,
                    "history_count": len(conversation_history or []),
                },
            )

            context_result = self._prepare_conversation_context(
                user_id=user_id,
                user_message=user_message,
                conversation_history=conversation_history,
                language=language,
                agent_profile=agent_profile,
                datetime_directive=await self._resolve_datetime_directive(db, user_id),
            )
            base_messages = list(context_result.messages)

            stream_context_usage = context_result.token_usage or {}
            stream_context_messages_selected = len(context_result.selected_history)
            stream_context_messages_dropped = len(context_result.dropped_history)
            stream_context_box_selected = sum(
                1
                for msg in context_result.selected_history
                if getattr(msg, "source", None) == "context_box"
            )
            stream_context_box_dropped = sum(
                1
                for msg in context_result.dropped_history
                if getattr(msg, "source", None) == "context_box"
            )

            self.context_pipeline.log_context_truncation(
                user_id=user_id,
                session_id=session_id,
                context_result=context_result,
            )

            tool_runs = []
            stream_snapshot = StreamingContextSnapshot(
                context_token_usage=stream_context_usage,
                context_messages_selected=stream_context_messages_selected,
                context_messages_dropped=stream_context_messages_dropped,
                context_box_messages_selected=stream_context_box_selected,
                context_box_messages_dropped=stream_context_box_dropped,
                context_budget_tokens=settings.conversation_context_budget,
                context_window_tokens=self.context_window_tokens,
                tool_runs=tool_runs,
            )

            session_was_provided = session_id is not None
            incoming_session_id = session_id
            if not session_id:
                session_id = uuid4()
                stream_log_context["session_id"] = str(session_id)
                runtime.set_session_id(session_id)
                logger.info(
                    "Generated new streaming session identifier",
                    extra={
                        **stream_log_context,
                        "action": "agent.stream.session_generated",
                    },
                )

            cardbox_session = await self.tool_executor.resolve_session_for_cardbox(
                db,
                session_id_value=incoming_session_id,
                user_id=user_id,
                session_was_provided=session_was_provided,
            )
            runtime.set_cardbox_session(cardbox_session)
            logger.info(
                "Resolved streaming Cardbox session",
                extra={
                    **stream_log_context,
                    "action": "agent.stream.cardbox_session",
                    "cardbox_box": getattr(cardbox_session, "cardbox_name", None),
                },
            )

            if context_summaries:
                tenant_id = tenant_for_user(user_id)
                self.context_pipeline.append_context_usage_log(
                    session=cardbox_session,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    summaries=context_summaries,
                )

            if (
                context_result.summary_candidates
                and cardbox_session is not None
                and session_id is not None
            ):
                summary_result = await self.conversation_compressor.compress(
                    session=cardbox_session,
                    user_id=user_id,
                    language=language,
                    candidates=context_result.summary_candidates,
                )
                if summary_result:
                    base_messages.insert(
                        1,
                        {
                            "role": summary_result.message.role,
                            "content": summary_result.message.content,
                        },
                    )
                    logger.info(
                        "Inserted streaming summary",
                        extra={
                            **stream_log_context,
                            "action": "agent.stream.summary_inserted",
                            "covered_messages": (
                                summary_result.message.metadata.get(
                                    "covered_messages", []
                                )
                                if summary_result.message.metadata
                                else []
                            ),
                            "card_id": summary_result.card_id,
                        },
                    )

            conversation_messages = list(base_messages)
            tool_iterations = 0
            total_tool_time = 0.0
            stream_loop_iterations = 0

            while True:
                stream_loop_iterations += 1
                detection_start = time.time()
                logger.info(
                    "Streaming agent loop iteration %s starting (tool_iterations=%s)",
                    stream_loop_iterations,
                    tool_iterations,
                    extra=stream_log_context,
                )
                detection_params = self._build_litellm_params(
                    messages=conversation_messages,
                    tools=tools,
                    tool_choice="auto",
                    metadata={
                        "message_id": message_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "is_stream_preview": True,
                        "tool_round": tool_iterations,
                    },
                    llm_overrides=llm_overrides,
                )

                try:
                    async with litellm_call_context(
                        logger=logger,
                        operation_name="LiteLLM call for streaming tool detection",
                        timeout=self.timeout,
                        error_cls=AgentServiceError,
                        extra_context={
                            "model": detection_params.get("model"),
                            "tools_count": len(tools) if tools else 0,
                        },
                    ) as (call_start_time, context):
                        logger.debug("LiteLLM call details:")
                        logger.debug(f"  Model: {detection_params.get('model')}")
                        logger.debug(
                            f"  Base URL: {detection_params.get('api_base', 'default')}"
                        )
                        logger.debug(
                            f"  Messages count: {len(detection_params.get('messages', []))}"
                        )
                        logger.debug(
                            f"  Tools count: {len(detection_params.get('tools', []))}"
                        )

                        execution_params = dict(detection_params)
                        detection_response = await asyncio.wait_for(
                            self.llm.completion(
                                messages=execution_params.pop("messages"),
                                metadata=execution_params.pop("metadata", None),
                                **execution_params,
                            ),
                            timeout=self.timeout,
                        )
                        logger.info(
                            "Streaming agent loop iteration %s received LLM response in %.2fs",
                            stream_loop_iterations,
                            time.time() - detection_start,
                            extra=stream_log_context,
                        )

                        time.time() - call_start_time
                        logger.debug(
                            f"LiteLLM response model: {getattr(detection_response, 'model', 'unknown')}"
                        )
                        logger.debug(
                            f"LiteLLM response usage: {getattr(detection_response, 'usage', 'no usage info')}"
                        )

                except AgentServiceError as exc:
                    yield AgentStreamEvent(
                        event="error",
                        data={
                            "message": f"AI service temporarily unavailable: {str(exc)}"
                        },
                    )
                    return

                assistant_message = detection_response.choices[0].message
                tool_calls = getattr(assistant_message, "tool_calls", None) or []
                logger.info(
                    "Streaming agent loop iteration %s parsed %s tool calls",
                    stream_loop_iterations,
                    len(tool_calls),
                    extra=stream_log_context,
                )
                logger.info(
                    "Tool detection result: %s tool calls requested",
                    len(tool_calls),
                )

                if not tool_calls:
                    if tool_iterations == 0:
                        logger.info(
                            "No tool calls detected, proceeding with direct streaming response"
                        )
                    else:
                        logger.info(
                            "Tool execution phase completed in %.2fs across %s round(s), starting final streaming response",
                            total_tool_time,
                            tool_iterations,
                        )
                    break

                tool_iterations += 1
                if tool_iterations > self.max_tool_rounds:
                    logger.warning(
                        "Streaming tool loop exceeded %s rounds",
                        self.max_tool_rounds,
                        extra=stream_log_context,
                    )
                    result = self.streaming_manager.build_fallback_result(
                        content="Tool invocation limit reached. Please refine your request.",
                        snapshot=stream_snapshot,
                    )
                    yield AgentStreamEvent(
                        event="final",
                        data=serialize_agent_result(result),
                    )
                    return

                logger.info(
                    "LLM requested %s tool calls during streaming round %s (loop iteration %s)",
                    len(tool_calls),
                    tool_iterations,
                    stream_loop_iterations,
                )
                logger.debug(
                    f"Tool calls details: {[(tc.function.name, tc.function.arguments) for tc in tool_calls]}"
                )

                tool_call_message = self.tool_executor.build_tool_call_message(
                    assistant_message
                )
                logger.info(
                    f"[stream_response_with_tools] Tool call message: {tool_call_message}"
                )
                conversation_messages.append(tool_call_message)

                tool_execution_start = time.time()
                tool_counts = defaultdict(int)
                tool_failures: List[Dict[str, str]] = []
                ordered_stream_calls = list(self.tool_policy.order_calls(tool_calls))
                tool_sequence = 0
                prepared_calls: List[PreparedToolCall] = []
                for tool_call in ordered_stream_calls:
                    raw_function_name = getattr(tool_call.function, "name", None)
                    function_name = self.tool_executor.normalize_tool_name(
                        raw_function_name
                    )
                    try:
                        function_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}
                    tool_sequence += 1
                    run_record = self.tool_executor.create_tool_run_record(
                        tool_call_id=tool_call.id,
                        tool_name=(
                            function_name
                            if function_name
                            else (
                                str(raw_function_name)
                                if raw_function_name
                                else "invalid_tool"
                            )
                        ),
                        arguments=function_args,
                        sequence=tool_sequence,
                    )
                    tool_runs.append(run_record)
                    if not function_name:
                        invalid_event = await self.tool_executor.handle_invalid_tool_call(
                            tool_call=tool_call,
                            run_record=run_record,
                            reason="LLM returned a tool call without a valid function name",
                            error_kind="invalid_tool_call",
                            messages=conversation_messages,
                            tool_failures=tool_failures,
                            runtime=runtime,
                        )
                        yield invalid_event
                        continue

                    run_record["tool_name"] = function_name
                    try:
                        metadata = tool_registry.get_tool_metadata(function_name)
                    except ValueError as exc:
                        invalid_event = (
                            await self.tool_executor.handle_invalid_tool_call(
                                tool_call=tool_call,
                                run_record=run_record,
                                reason=str(exc),
                                error_kind="invalid_tool_call",
                                messages=conversation_messages,
                                tool_failures=tool_failures,
                                runtime=runtime,
                            )
                        )
                        yield invalid_event
                        continue
                    call_index = tool_counts[function_name] + 1
                    tool_counts[function_name] = call_index
                    prepared_calls.append(
                        PreparedToolCall(
                            tool_call=tool_call,
                            name=function_name,
                            arguments=function_args,
                            run_record=run_record,
                            metadata=metadata,
                            call_index=call_index,
                        )
                    )
                    yield AgentStreamEvent(
                        event="tool_started",
                        data=self.tool_executor.build_tool_event_payload(
                            run_record,
                            include_arguments=True,
                        ),
                    )

                planner = ToolExecutionPlanner()
                execution_plan = planner.plan(prepared_calls)

                for batch in execution_plan:
                    try:
                        batch_events = await self.tool_executor.execute_tool_batch(
                            batch=batch,
                            tool_registry=tool_registry,
                            note_reference_lookup=None,
                            runtime=runtime,
                            messages=conversation_messages,
                            tool_failures=tool_failures,
                        )
                    except Exception as exc:
                        log_exception(
                            logger,
                            f"Streaming tool batch execution failed: {exc}",
                            sys.exc_info(),
                        )
                        batch_primary = batch.calls[0] if batch.calls else None
                        if batch_primary:
                            run_record = batch_primary.run_record
                            run_record["status"] = "failed"
                            run_record["message"] = str(exc)
                            tool_failures.append(
                                {"tool": batch_primary.name, "reason": str(exc)}
                            )
                        continue

                    for event in batch_events:
                        yield event

                elapsed = time.time() - tool_execution_start
                total_tool_time += elapsed
                logger.info(
                    "Tool execution round %s completed in %.2fs",
                    tool_iterations,
                    elapsed,
                )

                if tool_failures:
                    failure_message = self.tool_executor.compose_tool_failure_message(
                        tool_failures
                    )
                    logger.warning(
                        "Streaming tool execution encountered failures",
                        extra={
                            **stream_log_context,
                            "action": "agent.stream.tool_failure_summary",
                            "failures": tool_failures,
                        },
                    )
                    result = self.streaming_manager.build_fallback_result(
                        content=failure_message,
                        snapshot=stream_snapshot,
                    )
                    yield AgentStreamEvent(
                        event="final",
                        data=serialize_agent_result(result),
                    )
                    return

                continue

            async for event in self.streaming_manager.stream_completion(
                messages=conversation_messages,
                metadata={
                    "message_id": message_id,
                    "session_id": session_id,
                    "user_id": user_id,
                    "agent_name": agent_name,
                    "is_final_response": True,
                },
                start_time=start_time,
                snapshot=stream_snapshot,
                overrides=llm_overrides,
            ):
                yield event

            total_time = time.time() - start_time
            logger.info(
                f"Streaming response completed successfully in {total_time:.2f}s"
            )

        except ImportError as exc:
            log_exception(logger, f"LiteLLM import error: {exc}", sys.exc_info())
            result = self.streaming_manager.build_fallback_result(
                content="LiteLLM not installed, falling back to regular response",
                snapshot=stream_snapshot,
            )
            yield AgentStreamEvent(
                event="final",
                data=serialize_agent_result(result),
            )
        except Exception as exc:
            log_exception(
                logger,
                f"Error in stream_response_with_tools: {str(exc)}",
                sys.exc_info(),
            )
            logger.error("Debug Information (streaming):")
            debug_manager.log_error_details(
                user_message,
                str(user_id),
                str(session_id),
                str(message_id),
                self.model,
                self.api_key,
            )
            logger.error(f"  Base URL: {self.base_url}")
            logger.error(f"  Exception Type: {type(exc).__name__}")
            logger.error(f"  Exception Details: {str(exc)}")
            raise AgentServiceError(f"Failed to stream response: {str(exc)}")

    # ------------------------------------------------------------------
    # Backwards-compatible helpers used by existing unit tests
    # ------------------------------------------------------------------


# Global service instance
agent_service = AgentService()
