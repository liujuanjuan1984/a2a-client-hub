"""Provider-private OpenCode discovery routes.

These routes intentionally stay under an ``opencode`` namespace because the
capability itself is provider-private, even though the resolved model selection
metadata written into invoke payloads is shared.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Type
from uuid import UUID

from fastapi import Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.error_codes import status_code_for_extension_error_code
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.integrations.a2a_extensions import get_a2a_extensions_service
from app.integrations.a2a_extensions.errors import (
    A2AExtensionContractError,
    A2AExtensionNotSupportedError,
    A2AExtensionUpstreamError,
)
from app.schemas.a2a_extension import (
    A2AExtensionResponse,
    A2AProviderDiscoveryRequest,
)
from app.utils.logging_redaction import redact_url_for_logging

logger = get_logger(__name__)

BuildRuntimeFn = Callable[..., Awaitable[Any]]


def create_opencode_provider_discovery_router(
    *,
    prefix: str,
    build_runtime: BuildRuntimeFn,
    runtime_not_found_error: Type[Exception],
    runtime_validation_error: Type[Exception],
    runtime_validation_status_code: int,
    log_scope: str,
) -> StrictAPIRouter:
    router = StrictAPIRouter(prefix=prefix, tags=["a2a-opencode-discovery"])

    def _scope_message(message: str) -> str:
        return f"{log_scope} {message}".strip()

    async def _get_runtime(db: AsyncSession, current_user: User, agent_id: UUID) -> Any:
        try:
            return await build_runtime(db, user_id=current_user.id, agent_id=agent_id)
        except runtime_not_found_error as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except runtime_validation_error as exc:
            raise HTTPException(
                status_code=runtime_validation_status_code, detail=str(exc)
            ) from exc

    def _to_extension_response(result: Any) -> A2AExtensionResponse:
        return A2AExtensionResponse(
            success=result.success,
            result=result.result,
            error_code=result.error_code,
            upstream_error=result.upstream_error,
            meta=result.meta or {},
        )

    async def _run_extension_call(
        call: Awaitable[Any],
    ) -> A2AExtensionResponse | JSONResponse:
        try:
            result = await call
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (A2AExtensionNotSupportedError, A2AExtensionContractError) as exc:
            error_code = (
                "not_supported"
                if isinstance(exc, A2AExtensionNotSupportedError)
                else "extension_contract_error"
            )
            payload = A2AExtensionResponse(
                success=False,
                result=None,
                error_code=error_code,
                upstream_error={"message": str(exc)},
                meta={},
            )
            return JSONResponse(
                status_code=status_code_for_extension_error_code(error_code),
                content=payload.model_dump(),
            )
        except A2AExtensionUpstreamError as exc:
            payload = A2AExtensionResponse(
                success=False,
                result=None,
                error_code=exc.error_code,
                upstream_error=exc.upstream_error,
                meta={},
            )
            return JSONResponse(
                status_code=status_code_for_extension_error_code(exc.error_code),
                content=payload.model_dump(),
            )

        response = _to_extension_response(result)
        status_code = status_code_for_extension_error_code(response.error_code)
        if response.success or status_code == status.HTTP_200_OK:
            return response
        return JSONResponse(status_code=status_code, content=response.model_dump())

    @router.post(
        "/{agent_id}/extensions/opencode/providers:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_opencode_providers(
        *,
        agent_id: UUID,
        payload: A2AProviderDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime(db, current_user, agent_id)
        logger.info(
            _scope_message("OpenCode provider discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "metadata_keys": sorted((payload.metadata or {}).keys())[:20],
            },
        )
        return await _run_extension_call(
            get_a2a_extensions_service().list_opencode_providers(
                runtime=runtime,
                metadata=payload.metadata,
            )
        )

    @router.post(
        "/{agent_id}/extensions/opencode/models:list",
        response_model=A2AExtensionResponse,
        status_code=status.HTTP_200_OK,
    )
    async def list_opencode_models(
        *,
        agent_id: UUID,
        payload: A2AProviderDiscoveryRequest,
        response: Response,
        db: AsyncSession = Depends(get_async_db),
        current_user: User = Depends(get_current_user),
    ) -> A2AExtensionResponse | JSONResponse:
        response.headers["Cache-Control"] = "no-store"
        runtime = await _get_runtime(db, current_user, agent_id)
        logger.info(
            _scope_message("OpenCode model discovery requested"),
            extra={
                "user_id": str(current_user.id),
                "agent_id": str(agent_id),
                "agent_url": redact_url_for_logging(runtime.resolved.url),
                "provider_id": payload.provider_id,
                "metadata_keys": sorted((payload.metadata or {}).keys())[:20],
            },
        )
        return await _run_extension_call(
            get_a2a_extensions_service().list_opencode_models(
                runtime=runtime,
                provider_id=payload.provider_id,
                metadata=payload.metadata,
            )
        )

    return router


__all__ = ["create_opencode_provider_discovery_router"]
