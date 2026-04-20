"""User-facing router for the swival-backed Hub Assistant."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_async_db, get_current_user
from app.api.error_handlers import build_error_detail
from app.api.routing import StrictAPIRouter
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.transaction import commit_safely
from app.features.hub_assistant.schemas import (
    HubAssistantContinuation,
    HubAssistantInterrupt,
    HubAssistantInterruptDetails,
    HubAssistantInterruptRecoveryRequest,
    HubAssistantInterruptRecoveryResponse,
    HubAssistantInterruptReplyRequest,
    HubAssistantProfileResponse,
    HubAssistantRecoveredInterrupt,
    HubAssistantRunRequest,
    HubAssistantRunResponse,
    HubAssistantToolResponse,
)
from app.features.hub_assistant.service import (
    HubAssistantConfigError,
    HubAssistantRunResult,
    HubAssistantUnavailableError,
    hub_assistant_service,
)

router = StrictAPIRouter(
    prefix="/me/hub-assistant",
    tags=["hub-assistant"],
)
logger = get_logger(__name__)

_HUB_ASSISTANT_PERMISSION_REPLY_INVALID_OR_EXPIRED_DETAIL = (
    "The write approval request is invalid or expired."
)


def _permission_reply_error_detail(
    exc: HubAssistantUnavailableError,
) -> tuple[int, str | dict[str, str]]:
    message = str(exc)
    if message == _HUB_ASSISTANT_PERMISSION_REPLY_INVALID_OR_EXPIRED_DETAIL:
        return status.HTTP_409_CONFLICT, build_error_detail(
            message=message,
            error_code="interrupt_request_expired",
        )
    return status.HTTP_400_BAD_REQUEST, message


def _to_run_response(
    result: HubAssistantRunResult,
) -> HubAssistantRunResponse:
    interrupt = None
    if result.interrupt is not None:
        interrupt = HubAssistantInterrupt(
            requestId=result.interrupt.request_id,
            type="permission",
            phase="asked",
            details=HubAssistantInterruptDetails(
                permission=result.interrupt.permission,
                patterns=list(result.interrupt.patterns),
                displayMessage=result.interrupt.display_message,
            ),
        )

    return HubAssistantRunResponse(
        status=result.status.value,
        answer=result.answer,
        exhausted=result.exhausted,
        runtime=result.runtime,
        resources=list(result.resources),
        tools=list(result.tool_names),
        write_tools_enabled=result.write_tools_enabled,
        interrupt=interrupt,
        continuation=(
            HubAssistantContinuation(
                phase="running",
                agentMessageId=result.continuation.agent_message_id,
            )
            if result.continuation is not None
            else None
        ),
    )


@router.get("", response_model=HubAssistantProfileResponse)
async def get_hub_assistant_profile(
    _current_user: User = Depends(get_current_user),
) -> HubAssistantProfileResponse:
    profile = hub_assistant_service.get_profile()
    return HubAssistantProfileResponse(
        id=profile.agent_id,
        name=profile.name,
        description=profile.description,
        runtime=profile.runtime,
        configured=profile.configured,
        resources=list(profile.resources),
        tools=[
            HubAssistantToolResponse(
                operation_id=item.operation_id,
                tool_name=item.tool_name,
                description=item.description,
                confirmation_policy=item.confirmation_policy.value,
            )
            for item in profile.tool_definitions
        ],
    )


@router.post(":run", response_model=HubAssistantRunResponse)
async def run_hub_assistant(
    payload: HubAssistantRunRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HubAssistantRunResponse:
    try:
        result = await hub_assistant_service.run(
            db=db,
            current_user=current_user,
            conversation_id=payload.conversation_id,
            message=payload.message,
            user_message_id=payload.user_message_id,
            agent_message_id=payload.agent_message_id,
            allow_write_tools=payload.allow_write_tools,
        )
    except HubAssistantConfigError as exc:
        logger.exception(
            "Hub Assistant run misconfigured",
            extra={
                "user_id": str(current_user.id),
                "conversation_id": payload.conversation_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HubAssistantUnavailableError as exc:
        logger.exception(
            "Hub Assistant run failed",
            extra={
                "user_id": str(current_user.id),
                "conversation_id": payload.conversation_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception:
        logger.exception(
            "Hub Assistant run raised an unexpected error",
            extra={
                "user_id": str(current_user.id),
                "conversation_id": payload.conversation_id,
            },
        )
        raise

    await commit_safely(db)
    return _to_run_response(result)


@router.post(
    "/interrupts:recover",
    response_model=HubAssistantInterruptRecoveryResponse,
)
async def recover_hub_assistant_interrupts(
    payload: HubAssistantInterruptRecoveryRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HubAssistantInterruptRecoveryResponse:
    try:
        items = await hub_assistant_service.recover_pending_interrupts(
            db=db,
            current_user=current_user,
            conversation_id=payload.conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    await commit_safely(db)

    return HubAssistantInterruptRecoveryResponse(
        items=[
            HubAssistantRecoveredInterrupt(
                requestId=item.request_id,
                sessionId=item.session_id,
                type="permission",
                phase="asked",
                details=HubAssistantInterruptDetails(
                    permission=item.details.get("permission"),
                    patterns=list(item.details.get("patterns") or []),
                    displayMessage=item.details.get("displayMessage")
                    or item.details.get("display_message"),
                ),
            )
            for item in items
        ]
    )


@router.post(
    "/interrupts/permission:reply",
    response_model=HubAssistantRunResponse,
)
async def reply_hub_assistant_permission_interrupt(
    payload: HubAssistantInterruptReplyRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
) -> HubAssistantRunResponse:
    try:
        result = await hub_assistant_service.reply_permission_interrupt(
            db=db,
            current_user=current_user,
            request_id=payload.request_id,
            reply=payload.reply,
            agent_message_id=payload.agent_message_id,
        )
    except HubAssistantConfigError as exc:
        logger.exception(
            "Hub Assistant permission reply misconfigured",
            extra={
                "user_id": str(current_user.id),
                "request_id": payload.request_id,
                "reply": payload.reply,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except HubAssistantUnavailableError as exc:
        status_code, detail = _permission_reply_error_detail(exc)
        logger.exception(
            "Hub Assistant permission reply failed",
            extra={
                "user_id": str(current_user.id),
                "request_id": payload.request_id,
                "reply": payload.reply,
            },
        )
        raise HTTPException(
            status_code=status_code,
            detail=detail,
        ) from exc
    except Exception:
        logger.exception(
            "Hub Assistant permission reply raised an unexpected error",
            extra={
                "user_id": str(current_user.id),
                "request_id": payload.request_id,
                "reply": payload.reply,
            },
        )
        raise

    await commit_safely(db)
    if result.continuation is not None:
        from app.features.hub_assistant_shared.task_job import (
            request_hub_assistant_task_run,
        )

        request_hub_assistant_task_run()
    return _to_run_response(result)
