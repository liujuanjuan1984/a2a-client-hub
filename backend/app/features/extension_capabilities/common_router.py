"""Shared capability routes for session query and interrupt callbacks.

The hub catalog and user-managed agents expose the same shared extension
surface area but require different runtime builders and error semantics.
This module centralises the route implementations to avoid drift.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Type, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.transaction import load_for_external_call
from app.features.extension_capabilities import common_router_support
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_runtime_status_contract import (
    runtime_status_contract_payload,
)
from app.schemas.a2a_extension import (
    A2ACodexDiscoveryAppsListResponse,
    A2ACodexDiscoveryPluginReadRequest,
    A2ACodexDiscoveryPluginReadResponse,
    A2ACodexDiscoveryPluginsListResponse,
    A2ACodexDiscoverySkillsListResponse,
    A2AExtensionCapabilitiesResponse,
    A2AExtensionElicitationReplyRequest,
    A2AExtensionInterruptRecoveryRequest,
    A2AExtensionPermissionReplyRequest,
    A2AExtensionPermissionsReplyRequest,
    A2AExtensionPromptAsyncRequest,
    A2AExtensionQueryResponse,
    A2AExtensionQuestionRejectRequest,
    A2AExtensionQuestionReplyRequest,
    A2AExtensionResponse,
    A2AExtensionSessionCommandRequest,
    A2AExtensionSessionListQueryRequest,
    A2AExtensionSessionMessagesQueryRequest,
    A2AExtensionSessionMutationRequest,
    A2AInterruptRecoveryResponse,
    A2AModelDiscoveryRequest,
    A2ARuntimeStatusContractResponse,
)
from app.utils.logging_redaction import redact_url_for_logging

logger = get_logger(__name__)

BuildRuntimeFn = Callable[..., Awaitable[Any]]


def create_extension_capability_router(
    *,
    prefix: str,
    build_runtime: BuildRuntimeFn,
    runtime_not_found_error: Type[Exception],
    runtime_validation_error: Type[Exception],
    runtime_validation_status_code: int,
    log_scope: str,
) -> StrictAPIRouter:
    router = StrictAPIRouter(prefix=prefix, tags=["a2a-extensions"])

    def _scope_message(message: str) -> str:
        return f"{log_scope} {message}".strip()

    async def _get_runtime(db: AsyncSession, current_user: User, agent_id: UUID) -> Any:
        current_user_id = cast(UUID, current_user.id)
        try:
            return await build_runtime(db, user_id=current_user_id, agent_id=agent_id)
        except runtime_not_found_error as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except runtime_validation_error as exc:
            raise HTTPException(
                status_code=runtime_validation_status_code, detail=str(exc)
            ) from exc

    async def _get_runtime_for_external_call(
        db: AsyncSession,
        current_user: User,
        agent_id: UUID,
    ) -> Any:
        return await load_for_external_call(
            db,
            lambda session: _get_runtime(session, current_user, agent_id),
        )

    def _extensions_service() -> Any:
        return cast(Any, get_a2a_extensions_service())

    @router.get(
        "/{agent_id}/extensions/capabilities",
        response_model=A2AExtensionCapabilitiesResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_extension_capabilities(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionCapabilitiesResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        snapshot = await _extensions_service().resolve_capability_snapshot(
            runtime=runtime
        )
        model_selection = snapshot.model_selection.status == "supported"
        provider_discovery = snapshot.provider_discovery.status == "supported"
        interrupt_recovery = snapshot.interrupt_recovery.status == "supported"
        session_control = common_router_support.build_session_control_response(snapshot)
        session_prompt_async = (
            session_control.prompt_async.declared
            and session_control.prompt_async.consumed_by_hub
        )

        return A2AExtensionCapabilitiesResponse(
            modelSelection=model_selection,
            providerDiscovery=provider_discovery,
            interruptRecovery=interrupt_recovery,
            interruptRecoveryDetails=common_router_support.build_interrupt_recovery_details_response(
                snapshot
            ),
            sessionPromptAsync=session_prompt_async,
            sessionControl=session_control,
            invokeMetadata=common_router_support.build_invoke_metadata_response(
                snapshot
            ),
            requestExecutionOptions=common_router_support.build_request_execution_options_response(
                snapshot
            ),
            streamHints=common_router_support.build_stream_hints_response(snapshot),
            wireContract=common_router_support.build_wire_contract_response(snapshot),
            compatibilityProfile=common_router_support.build_compatibility_profile_response(
                snapshot
            ),
            codexDiscovery=common_router_support.build_declared_method_collection_response(
                getattr(snapshot, "codex_discovery", None)
            ),
            codexThreads=common_router_support.build_declared_method_collection_response(
                getattr(snapshot, "codex_threads", None)
            ),
            codexTurns=common_router_support.build_declared_method_collection_response(
                getattr(snapshot, "codex_turns", None)
            ),
            codexReview=common_router_support.build_declared_method_collection_response(
                getattr(snapshot, "codex_review", None)
            ),
            codexThreadWatch=common_router_support.build_declared_single_method_response(
                getattr(snapshot, "codex_thread_watch", None)
            ),
            codexExec=common_router_support.build_declared_method_collection_response(
                getattr(snapshot, "codex_exec", None)
            ),
            runtimeStatus=A2ARuntimeStatusContractResponse.model_validate(
                runtime_status_contract_payload()
            ),
        )

    @router.post(
        "/{agent_id}/extensions/models/providers:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_model_providers(
        *,
        agent_id: UUID,
        payload: A2AModelDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Generic model provider discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.session_metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().list_model_providers(
                runtime=runtime,
                session_metadata=payload.session_metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/models:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_models(
        *,
        agent_id: UUID,
        payload: A2AModelDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Generic model discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "provider_id": payload.provider_id,
                "session_metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.session_metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().list_models(
                runtime=runtime,
                provider_id=payload.provider_id,
                session_metadata=payload.session_metadata,
            )
        )

    @router.get(
        "/{agent_id}/extensions/codex/skills",
        response_model=A2ACodexDiscoverySkillsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_skills(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery skills list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().list_codex_skills(runtime=runtime)
        )

    @router.get(
        "/{agent_id}/extensions/codex/apps",
        response_model=A2ACodexDiscoveryAppsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_apps(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery apps list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().list_codex_apps(runtime=runtime)
        )

    @router.get(
        "/{agent_id}/extensions/codex/plugins",
        response_model=A2ACodexDiscoveryPluginsListResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_codex_plugins(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery plugins list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().list_codex_plugins(runtime=runtime)
        )

    @router.post(
        "/{agent_id}/extensions/codex/plugins:read",
        response_model=A2ACodexDiscoveryPluginReadResponse,
        status_code=status.HTTP_200_OK,
    )
    async def read_codex_plugin(
        *,
        agent_id: UUID,
        payload: A2ACodexDiscoveryPluginReadRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Codex discovery plugin read requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "marketplace_path": payload.marketplace_path,
                "plugin_name": payload.plugin_name,
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().read_codex_plugin(
                runtime=runtime,
                marketplace_path=payload.marketplace_path,
                plugin_name=payload.plugin_name,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def list_external_sessions(
        *,
        agent_id: UUID,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: Optional[int] = Query(
            None, ge=1, description="Page size (uses card default when omitted)"
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
        directory: Optional[str] = Query(
            None,
            min_length=1,
            description="Optional Hub session list directory filter",
        ),
        roots: Optional[bool] = Query(
            None,
            description="Optional Hub roots-only filter for session list",
        ),
        start: Optional[int] = Query(
            None,
            ge=0,
            description="Optional Hub session list start offset filter",
        ),
        search: Optional[str] = Query(
            None,
            min_length=1,
            description="Optional Hub session list search filter",
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        query_obj = common_router_support.parse_query_param(query)
        filter_obj = common_router_support.build_session_list_filters(
            directory=directory,
            roots=roots,
            start=start,
            search=search,
        )
        logger.info(
            _scope_message("Shared extension sessions list requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": page,
                "size": size,
                "include_raw": include_raw,
                "filter_meta": common_router_support.summarize_session_list_filters(
                    filter_obj
                ),
                "query_meta": common_router_support.summarize_query_object(query_obj),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().list_sessions(
                runtime=runtime,
                page=page,
                size=size,
                include_raw=include_raw,
                query=query_obj,
                filters=filter_obj,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:continue",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def continue_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session continue requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().continue_session(
                runtime=runtime,
                session_id=session_id,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:prompt-async",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def prompt_external_session_async(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionPromptAsyncRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        request_keys = sorted(payload.request.keys())[:20]
        metadata_keys = common_router_support.summarize_metadata_keys(payload.metadata)
        logger.info(
            _scope_message("Shared extension session prompt_async requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": request_keys,
                "request_parts_count": (
                    len(payload.request.get("parts", []))
                    if isinstance(payload.request.get("parts"), list)
                    else None
                ),
                "metadata_keys": metadata_keys,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().prompt_session_async(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:command",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def command_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionCommandRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        request_keys = sorted(payload.request.keys())[:20]
        metadata_keys = common_router_support.summarize_metadata_keys(payload.metadata)
        logger.info(
            _scope_message("Shared extension session command requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": request_keys,
                "metadata_keys": metadata_keys,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().command_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session detail requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/children",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_children(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session children requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_children(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/todo",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_todo(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session todo requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "include_raw": include_raw,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_todo(
                runtime=runtime,
                session_id=session_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/diff",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_diff(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        message_id: Optional[str] = Query(
            None,
            alias="messageId",
            min_length=1,
            description="Optional message id used to narrow the diff lookup",
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session diff requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_diff(
                runtime=runtime,
                session_id=session_id,
                message_id=message_id,
                include_raw=include_raw,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/messages/{message_id}",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def get_external_session_message(
        *,
        agent_id: UUID,
        session_id: str,
        message_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session message requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "message_id": message_id,
                "include_raw": include_raw,
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_message(
                runtime=runtime,
                session_id=session_id,
                message_id=message_id,
                include_raw=include_raw,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:fork",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def fork_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session fork requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().fork_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:share",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def share_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session share requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().share_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:unshare",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def unshare_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session unshare requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().unshare_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:summarize",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def summarize_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session summarize requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().summarize_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:revert",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def revert_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session revert requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "request_keys": sorted((payload.request or {}).keys())[:20],
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().revert_session(
                runtime=runtime,
                session_id=session_id,
                request_payload=payload.request or {},
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}:unrevert",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def unrevert_external_session(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMutationRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session unrevert requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().unrevert_session(
                runtime=runtime,
                session_id=session_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts:recover",
        response_model=A2AInterruptRecoveryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def recover_interrupts(
        *,
        agent_id: UUID,
        payload: A2AExtensionInterruptRecoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AInterruptRecoveryResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension interrupt recovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": payload.session_id,
            },
        )

        result = await common_router_support.run_extension_call(
            _extensions_service().recover_interrupts(
                runtime=runtime,
                session_id=payload.session_id,
            )
        )
        if isinstance(result, JSONResponse):
            return result
        resolved_result = (
            result.result if isinstance(result.result, dict) else {"items": []}
        )
        items = resolved_result.get("items")
        return A2AInterruptRecoveryResponse.model_validate(
            {"items": items if isinstance(items, list) else []}
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/permission:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_permission_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionPermissionReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension permission interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "reply": payload.reply,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().reply_permission_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                reply=payload.reply,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/question:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_question_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionQuestionReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension question interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "answers_count": len(payload.answers),
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().reply_question_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                answers=payload.answers,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/question:reject",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reject_question_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionQuestionRejectRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension question interrupt reject requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().reject_question_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/permissions:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_permissions_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionPermissionsReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension permissions interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "scope": payload.scope,
                "permissions_meta": common_router_support.summarize_object_keys(
                    payload.permissions
                ),
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().reply_permissions_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                permissions=payload.permissions,
                scope=payload.scope,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/interrupts/elicitation:reply",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def reply_elicitation_interrupt(
        *,
        agent_id: UUID,
        payload: A2AExtensionElicitationReplyRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension elicitation interrupt reply requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "request_id": payload.request_id,
                "action": payload.action,
                "has_content": payload.content is not None,
                "metadata_keys": common_router_support.summarize_metadata_keys(
                    payload.metadata
                ),
            },
        )
        return await common_router_support.run_extension_call(
            _extensions_service().reply_elicitation_interrupt(
                runtime=runtime,
                request_id=payload.request_id,
                action=payload.action,
                content=payload.content,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions:query",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def query_external_sessions(
        *,
        agent_id: UUID,
        payload: A2AExtensionSessionListQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        filters = (
            payload.filters.model_dump(exclude_none=True)
            if payload.filters is not None
            else None
        )
        logger.info(
            _scope_message("Shared extension sessions list requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "page": payload.page,
                "size": payload.size,
                "include_raw": payload.include_raw,
                "filter_meta": common_router_support.summarize_session_list_filters(
                    filters
                ),
                "query_meta": common_router_support.summarize_query_object(
                    payload.query
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().list_sessions(
                runtime=runtime,
                page=payload.page,
                size=payload.size,
                include_raw=payload.include_raw,
                query=payload.query,
                filters=filters,
            )
        )

    @router.get(
        "/{agent_id}/extensions/sessions/{session_id}/messages",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def list_external_session_messages(
        *,
        agent_id: UUID,
        session_id: str,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
        page: int = Query(1, ge=1, description="Page number (1-indexed)"),
        size: Optional[int] = Query(
            None, ge=1, description="Page size (uses card default when omitted)"
        ),
        before: Optional[str] = Query(
            None,
            min_length=1,
            description=(
                "Opaque cursor for loading older session messages when supported "
                "by the runtime contract"
            ),
        ),
        include_raw: bool = Query(
            False,
            description="Whether to include the upstream raw payload in the response",
        ),
        query: Optional[str] = Query(
            None, description="Optional JSON object encoded as a string"
        ),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        query_obj = common_router_support.parse_query_param(query)
        logger.info(
            _scope_message("Shared extension session messages requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": page,
                "size": size,
                "before": before,
                "include_raw": include_raw,
                "query_meta": common_router_support.summarize_query_object(query_obj),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=page,
                size=size,
                before=before,
                include_raw=include_raw,
                query=query_obj,
            )
        )

    @router.post(
        "/{agent_id}/extensions/sessions/{session_id}/messages:query",
        response_model=A2AExtensionQueryResponse,
        status_code=status.HTTP_200_OK,
        response_model_exclude_none=True,
    )
    async def query_external_session_messages(
        *,
        agent_id: UUID,
        session_id: str,
        payload: A2AExtensionSessionMessagesQueryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"

        runtime = await _get_runtime_for_external_call(db, current_user, agent_id)
        logger.info(
            _scope_message("Shared extension session messages requested (POST)"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "session_id": session_id,
                "page": payload.page,
                "size": payload.size,
                "before": payload.before,
                "include_raw": payload.include_raw,
                "query_meta": common_router_support.summarize_query_object(
                    payload.query
                ),
            },
        )

        return await common_router_support.run_extension_call(
            _extensions_service().get_session_messages(
                runtime=runtime,
                session_id=session_id,
                page=payload.page,
                size=payload.size,
                before=payload.before,
                include_raw=payload.include_raw,
                query=payload.query,
            )
        )

    return router
