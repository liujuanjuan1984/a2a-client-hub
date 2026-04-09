"""User-facing router for the swival-backed built-in self-management agent."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.routing import StrictAPIRouter
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.self_management_agent.schemas import (
    SelfManagementBuiltInAgentInterrupt,
    SelfManagementBuiltInAgentInterruptDetails,
    SelfManagementBuiltInAgentInterruptReplyRequest,
    SelfManagementBuiltInAgentProfileResponse,
    SelfManagementBuiltInAgentRunRequest,
    SelfManagementBuiltInAgentRunResponse,
    SelfManagementBuiltInAgentToolResponse,
)
from app.features.self_management_agent.service import (
    SelfManagementBuiltInAgentConfigError,
    SelfManagementBuiltInAgentRunResult,
    SelfManagementBuiltInAgentUnavailableError,
    self_management_built_in_agent_service,
)

router = StrictAPIRouter(
    prefix="/me/self-management/agent",
    tags=["self-management-agent"],
)


def _to_run_response(
    result: SelfManagementBuiltInAgentRunResult,
) -> SelfManagementBuiltInAgentRunResponse:
    interrupt = None
    if result.interrupt is not None:
        interrupt = SelfManagementBuiltInAgentInterrupt(
            requestId=result.interrupt.request_id,
            type="permission",
            phase="asked",
            details=SelfManagementBuiltInAgentInterruptDetails(
                permission=result.interrupt.permission,
                patterns=list(result.interrupt.patterns),
                displayMessage=result.interrupt.display_message,
            ),
        )

    return SelfManagementBuiltInAgentRunResponse(
        status=result.status.value,
        answer=result.answer,
        exhausted=result.exhausted,
        runtime=result.runtime,
        resources=list(result.resources),
        tools=list(result.tool_names),
        write_tools_enabled=result.write_tools_enabled,
        interrupt=interrupt,
    )


@router.get("", response_model=SelfManagementBuiltInAgentProfileResponse)
async def get_self_management_built_in_agent_profile(
    _current_user: User = Depends(get_current_user),
) -> SelfManagementBuiltInAgentProfileResponse:
    profile = self_management_built_in_agent_service.get_profile()
    return SelfManagementBuiltInAgentProfileResponse(
        id=profile.agent_id,
        name=profile.name,
        description=profile.description,
        runtime=profile.runtime,
        configured=profile.configured,
        resources=list(profile.resources),
        tools=[
            SelfManagementBuiltInAgentToolResponse(
                operation_id=item.operation_id,
                tool_name=item.tool_name,
                description=item.description,
                confirmation_policy=item.confirmation_policy.value,
            )
            for item in profile.tool_definitions
        ],
    )


@router.post(":run", response_model=SelfManagementBuiltInAgentRunResponse)
async def run_self_management_built_in_agent(
    payload: SelfManagementBuiltInAgentRunRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SelfManagementBuiltInAgentRunResponse:
    try:
        result = await self_management_built_in_agent_service.run(
            db=db,
            current_user=current_user,
            conversation_id=payload.conversation_id,
            message=payload.message,
            allow_write_tools=payload.allow_write_tools,
        )
    except SelfManagementBuiltInAgentConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SelfManagementBuiltInAgentUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    await commit_safely(db)
    return _to_run_response(result)


@router.post(
    "/interrupts/permission:reply",
    response_model=SelfManagementBuiltInAgentRunResponse,
)
async def reply_self_management_built_in_agent_permission_interrupt(
    payload: SelfManagementBuiltInAgentInterruptReplyRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> SelfManagementBuiltInAgentRunResponse:
    try:
        result = (
            await self_management_built_in_agent_service.reply_permission_interrupt(
                db=db,
                current_user=current_user,
                request_id=payload.request_id,
                reply=payload.reply,
            )
        )
    except SelfManagementBuiltInAgentConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SelfManagementBuiltInAgentUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await commit_safely(db)
    return _to_run_response(result)
