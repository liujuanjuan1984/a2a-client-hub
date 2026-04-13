"""Shared self-management jobs service built on top of schedule domain services."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.user import User
from app.features.schedules.schemas import A2AScheduleTaskUpdate
from app.features.schedules.service import a2a_schedule_service
from app.features.self_management_shared.capability_catalog import (
    SELF_JOBS_CREATE,
    SELF_JOBS_DELETE,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway

logger = get_logger(__name__)


class SelfManagementJobsService:
    """Shared job operations for REST, CLI, and built-in agent entry points."""

    def _user_id(self, user: User) -> UUID:
        user_id = cast(UUID | None, user.id)
        if user_id is None:
            raise ValueError("Authenticated user id is required")
        return user_id

    def supports_prompt_update(self, payload: A2AScheduleTaskUpdate) -> bool:
        """Return whether the payload maps cleanly to the first-wave prompt update."""

        return (
            payload.prompt is not None
            and payload.name is None
            and payload.agent_id is None
            and payload.cycle_type is None
            and payload.time_point is None
            and payload.enabled is None
            and payload.conversation_policy is None
            and payload.schedule_timezone is None
        )

    def supports_schedule_update(self, payload: A2AScheduleTaskUpdate) -> bool:
        """Return whether the payload maps cleanly to the first-wave schedule update."""

        has_schedule_fields = (
            payload.cycle_type is not None
            or payload.time_point is not None
            or payload.schedule_timezone is not None
        )
        return (
            has_schedule_fields
            and payload.name is None
            and payload.agent_id is None
            and payload.prompt is None
            and payload.enabled is None
            and payload.conversation_policy is None
        )

    async def list_jobs(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        page: int,
        size: int,
    ) -> tuple[list[A2AScheduleTask], int]:
        result = await gateway.execute(
            operation=SELF_JOBS_LIST,
            handler=lambda: a2a_schedule_service.list_tasks(
                db,
                user_id=self._user_id(current_user),
                page=page,
                size=size,
            ),
        )
        return result.result

    async def get_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_GET,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.get_task(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
            ),
        )
        return result.result

    async def create_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        name: str,
        agent_id: UUID,
        prompt: str,
        cycle_type: str,
        time_point: dict[str, object],
        enabled: bool,
        conversation_policy: str,
        timezone_str: str,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_CREATE,
            handler=lambda: a2a_schedule_service.create_task(
                db,
                user_id=self._user_id(current_user),
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
                name=name,
                agent_id=agent_id,
                prompt=prompt,
                cycle_type=cycle_type,
                time_point=time_point,
                enabled=enabled,
                conversation_policy=conversation_policy,
            ),
        )
        logger.info(
            "Self-management job create requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def pause_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
        timezone_str: str,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_PAUSE,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.set_enabled(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
                enabled=False,
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
            ),
        )
        logger.info(
            "Self-management job pause requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def resume_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
        timezone_str: str,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_RESUME,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.set_enabled(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
                enabled=True,
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
            ),
        )
        logger.info(
            "Self-management job resume requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def update_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
        timezone_str: str,
        name: str | None = None,
        agent_id: UUID | None = None,
        prompt: str | None = None,
        cycle_type: str | None = None,
        time_point: dict[str, object] | None = None,
        enabled: bool | None = None,
        conversation_policy: str | None = None,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_UPDATE,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.update_task(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
                name=name,
                agent_id=agent_id,
                prompt=prompt,
                cycle_type=cycle_type,
                time_point=time_point,
                enabled=enabled,
                conversation_policy=conversation_policy,
            ),
        )
        logger.info(
            "Self-management job update requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def update_prompt(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
        prompt: str,
        timezone_str: str,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_UPDATE_PROMPT,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.update_task(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
                prompt=prompt,
            ),
        )
        logger.info(
            "Self-management job prompt update requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def update_schedule(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
        cycle_type: str | None,
        time_point: dict[str, object] | None,
        timezone_str: str,
    ) -> A2AScheduleTask:
        result = await gateway.execute(
            operation=SELF_JOBS_UPDATE_SCHEDULE,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.update_task(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
                is_superuser=bool(current_user.is_superuser),
                timezone_str=timezone_str,
                cycle_type=cycle_type,
                time_point=time_point,
            ),
        )
        logger.info(
            "Self-management job schedule update requested",
            extra=result.audit_fields.as_log_extra(),
        )
        return result.result

    async def delete_job(
        self,
        *,
        db: AsyncSession,
        gateway: SelfManagementToolGateway,
        current_user: User,
        task_id: UUID,
    ) -> None:
        result = await gateway.execute(
            operation=SELF_JOBS_DELETE,
            resource_id=str(task_id),
            handler=lambda: a2a_schedule_service.delete_task(
                db,
                user_id=self._user_id(current_user),
                task_id=task_id,
            ),
        )
        logger.info(
            "Self-management job delete requested",
            extra=result.audit_fields.as_log_extra(),
        )


self_management_jobs_service = SelfManagementJobsService()


__all__ = ["SelfManagementJobsService", "self_management_jobs_service"]
