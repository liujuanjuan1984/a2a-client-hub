"""Shared operation-oriented toolkit for self-management entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.user import User
from app.features.personal_agents.self_management_agents_service import (
    self_management_agents_service,
)
from app.features.personal_agents.service import A2AAgentRecord
from app.features.schedules.self_management_jobs_service import (
    self_management_jobs_service,
)
from app.features.self_management_shared.capability_catalog import (
    SELF_AGENTS_CHECK_HEALTH,
    SELF_AGENTS_CHECK_HEALTH_ALL,
    SELF_AGENTS_CREATE,
    SELF_AGENTS_DELETE,
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_START_SESSIONS,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_FOLLOWUPS_GET,
    SELF_FOLLOWUPS_SET_SESSIONS,
    SELF_JOBS_CREATE,
    SELF_JOBS_DELETE,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_ARCHIVE,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_GET_LATEST_MESSAGES,
    SELF_SESSIONS_LIST,
    SELF_SESSIONS_SEND_MESSAGE,
    SELF_SESSIONS_UNARCHIVE,
    SELF_SESSIONS_UPDATE,
    get_self_management_operation,
)
from app.features.self_management_shared.delegated_conversation_service import (
    self_management_delegated_conversation_service,
)
from app.features.self_management_shared.follow_up_service import (
    built_in_follow_up_service,
)
from app.features.self_management_shared.tool_gateway import SelfManagementToolGateway
from app.features.sessions.common import SessionSource
from app.features.sessions.self_management_sessions_service import (
    self_management_sessions_service,
)


class SelfManagementToolInputError(ValueError):
    """Raised when a self-management tool invocation has invalid inputs."""


@dataclass(frozen=True)
class SelfManagementToolExecutionResult:
    """One structured self-management tool execution result."""

    operation_id: str
    payload: dict[str, Any]


class SelfManagementToolkit:
    """Operation-oriented toolkit shared by CLI and future built-in agents."""

    def __init__(
        self,
        *,
        db: AsyncSession,
        current_user: User,
        gateway: SelfManagementToolGateway,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.gateway = gateway

    async def execute(
        self,
        *,
        operation_id: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> SelfManagementToolExecutionResult:
        args = dict(arguments or {})
        operation = get_self_management_operation(operation_id)
        if operation.operation_id == SELF_JOBS_LIST.operation_id:
            payload = await self._list_jobs(args)
        elif operation.operation_id == SELF_JOBS_GET.operation_id:
            payload = await self._get_job(args)
        elif operation.operation_id == SELF_JOBS_CREATE.operation_id:
            payload = await self._create_job(args)
        elif operation.operation_id == SELF_JOBS_PAUSE.operation_id:
            payload = await self._pause_job(args)
        elif operation.operation_id == SELF_JOBS_RESUME.operation_id:
            payload = await self._resume_job(args)
        elif operation.operation_id == SELF_JOBS_UPDATE.operation_id:
            payload = await self._update_job(args)
        elif operation.operation_id == SELF_JOBS_UPDATE_PROMPT.operation_id:
            payload = await self._update_job_prompt(args)
        elif operation.operation_id == SELF_JOBS_UPDATE_SCHEDULE.operation_id:
            payload = await self._update_job_schedule(args)
        elif operation.operation_id == SELF_JOBS_DELETE.operation_id:
            payload = await self._delete_job(args)
        elif operation.operation_id == SELF_SESSIONS_LIST.operation_id:
            payload = await self._list_sessions(args)
        elif operation.operation_id == SELF_SESSIONS_GET.operation_id:
            payload = await self._get_session(args)
        elif operation.operation_id == SELF_FOLLOWUPS_GET.operation_id:
            payload = await self._get_follow_up_state(args)
        elif operation.operation_id == SELF_FOLLOWUPS_SET_SESSIONS.operation_id:
            payload = await self._set_follow_up_sessions(args)
        elif operation.operation_id == SELF_SESSIONS_GET_LATEST_MESSAGES.operation_id:
            payload = await self._get_latest_session_messages(args)
        elif operation.operation_id == SELF_SESSIONS_UPDATE.operation_id:
            payload = await self._update_session(args)
        elif operation.operation_id == SELF_SESSIONS_ARCHIVE.operation_id:
            payload = await self._archive_session(args)
        elif operation.operation_id == SELF_SESSIONS_UNARCHIVE.operation_id:
            payload = await self._unarchive_session(args)
        elif operation.operation_id == SELF_SESSIONS_SEND_MESSAGE.operation_id:
            payload = await self._send_session_message(args)
        elif operation.operation_id == SELF_AGENTS_LIST.operation_id:
            payload = await self._list_agents(args)
        elif operation.operation_id == SELF_AGENTS_GET.operation_id:
            payload = await self._get_agent(args)
        elif operation.operation_id == SELF_AGENTS_CHECK_HEALTH.operation_id:
            payload = await self._check_agent_health(args)
        elif operation.operation_id == SELF_AGENTS_CHECK_HEALTH_ALL.operation_id:
            payload = await self._check_all_agents_health(args)
        elif operation.operation_id == SELF_AGENTS_CREATE.operation_id:
            payload = await self._create_agent(args)
        elif operation.operation_id == SELF_AGENTS_UPDATE_CONFIG.operation_id:
            payload = await self._update_agent_config(args)
        elif operation.operation_id == SELF_AGENTS_DELETE.operation_id:
            payload = await self._delete_agent(args)
        elif operation.operation_id == SELF_AGENTS_START_SESSIONS.operation_id:
            payload = await self._start_agent_sessions(args)
        else:  # pragma: no cover - defensive guard
            raise SelfManagementToolInputError(
                f"Operation `{operation_id}` is not implemented by the toolkit."
            )
        return SelfManagementToolExecutionResult(
            operation_id=operation_id,
            payload=payload,
        )

    async def _list_jobs(self, args: dict[str, Any]) -> dict[str, Any]:
        page = self._as_int(args.get("page", 1), field_name="page", minimum=1)
        size = self._as_int(args.get("size", 20), field_name="size", minimum=1)
        items, total = await self_management_jobs_service.list_jobs(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            page=page,
            size=size,
        )
        return {
            "items": [
                self._serialize_job(item, timezone_str=self._timezone_str())
                for item in items
            ],
            "page": page,
            "size": size,
            "total": total,
        }

    async def _get_job(self, args: dict[str, Any]) -> dict[str, Any]:
        task = await self_management_jobs_service.get_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
        )
        return {"job": self._serialize_job(task, timezone_str=self._timezone_str())}

    async def _create_job(self, args: dict[str, Any]) -> dict[str, Any]:
        schedule_timezone = (
            self._as_optional_str(args.get("schedule_timezone")) or self._timezone_str()
        )
        enabled = (
            cast(
                bool,
                self._as_optional_bool(args.get("enabled"), field_name="enabled"),
            )
            if args.get("enabled") is not None
            else True
        )
        task = await self_management_jobs_service.create_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            name=self._as_str(args.get("name"), field_name="name"),
            agent_id=self._as_uuid(args.get("agent_id"), field_name="agent_id"),
            prompt=self._as_str(args.get("prompt"), field_name="prompt"),
            cycle_type=self._as_str(args.get("cycle_type"), field_name="cycle_type"),
            time_point=(
                self._as_optional_dict(args.get("time_point"), field_name="time_point")
                or {}
            ),
            enabled=enabled,
            conversation_policy=(
                self._as_optional_str(args.get("conversation_policy")) or "new_each_run"
            ),
            timezone_str=schedule_timezone,
        )
        return {"job": self._serialize_job(task, timezone_str=schedule_timezone)}

    async def _pause_job(self, args: dict[str, Any]) -> dict[str, Any]:
        task = await self_management_jobs_service.pause_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
            timezone_str=self._timezone_str(),
        )
        return {"job": self._serialize_job(task, timezone_str=self._timezone_str())}

    async def _resume_job(self, args: dict[str, Any]) -> dict[str, Any]:
        task = await self_management_jobs_service.resume_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
            timezone_str=self._timezone_str(),
        )
        return {"job": self._serialize_job(task, timezone_str=self._timezone_str())}

    async def _update_job(self, args: dict[str, Any]) -> dict[str, Any]:
        schedule_timezone = (
            self._as_optional_str(args.get("schedule_timezone")) or self._timezone_str()
        )
        task = await self_management_jobs_service.update_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
            timezone_str=schedule_timezone,
            name=self._as_optional_str(args.get("name")),
            agent_id=self._as_optional_uuid(
                args.get("agent_id"), field_name="agent_id"
            ),
            prompt=self._as_optional_str(args.get("prompt")),
            cycle_type=self._as_optional_str(args.get("cycle_type")),
            time_point=self._as_optional_dict(
                args.get("time_point"),
                field_name="time_point",
            ),
            enabled=self._as_optional_bool(args.get("enabled"), field_name="enabled"),
            conversation_policy=self._as_optional_str(args.get("conversation_policy")),
        )
        return {"job": self._serialize_job(task, timezone_str=schedule_timezone)}

    async def _update_job_prompt(self, args: dict[str, Any]) -> dict[str, Any]:
        prompt = self._as_str(args.get("prompt"), field_name="prompt")
        task = await self_management_jobs_service.update_prompt(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
            prompt=prompt,
            timezone_str=self._timezone_str(),
        )
        return {"job": self._serialize_job(task, timezone_str=self._timezone_str())}

    async def _update_job_schedule(self, args: dict[str, Any]) -> dict[str, Any]:
        cycle_type = self._as_optional_str(args.get("cycle_type"))
        time_point = self._as_optional_dict(
            args.get("time_point"), field_name="time_point"
        )
        schedule_timezone = (
            self._as_optional_str(args.get("schedule_timezone")) or self._timezone_str()
        )
        task = await self_management_jobs_service.update_schedule(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=self._as_uuid(args.get("task_id"), field_name="task_id"),
            cycle_type=cycle_type,
            time_point=time_point,
            timezone_str=schedule_timezone,
        )
        return {"job": self._serialize_job(task, timezone_str=schedule_timezone)}

    async def _delete_job(self, args: dict[str, Any]) -> dict[str, Any]:
        task_id = self._as_uuid(args.get("task_id"), field_name="task_id")
        await self_management_jobs_service.delete_job(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            task_id=task_id,
        )
        return {"task_id": str(task_id), "deleted": True}

    async def _list_sessions(self, args: dict[str, Any]) -> dict[str, Any]:
        page = self._as_int(args.get("page", 1), field_name="page", minimum=1)
        size = self._as_int(args.get("size", 20), field_name="size", minimum=1)
        raw_source = self._as_optional_str(args.get("source"))
        source = self._as_session_source(raw_source)
        status = self._as_session_status(
            self._as_optional_str(args.get("status")) or "active"
        )
        agent_id = self._as_optional_uuid(args.get("agent_id"), field_name="agent_id")
        items, extra, _db_mutated = (
            await self_management_sessions_service.list_sessions(
                db=self.db,
                gateway=self.gateway,
                current_user=self.current_user,
                page=page,
                size=size,
                source=source,
                status=status,
                agent_id=agent_id,
            )
        )
        return {
            "items": [self._serialize_session(item) for item in items],
            "pagination": extra["pagination"],
        }

    async def _get_session(self, args: dict[str, Any]) -> dict[str, Any]:
        conversation_id = self._as_str(
            args.get("conversation_id"),
            field_name="conversation_id",
        )
        session_item = await self_management_sessions_service.get_session(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_id=conversation_id,
        )
        return {"session": self._serialize_session(session_item)}

    async def _get_follow_up_state(self, _args: dict[str, Any]) -> dict[str, Any]:
        return await built_in_follow_up_service.get_follow_up_state(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
        )

    async def _set_follow_up_sessions(self, args: dict[str, Any]) -> dict[str, Any]:
        return await built_in_follow_up_service.set_tracked_sessions(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_ids=self._as_optional_str_list(
                args.get("conversation_ids"),
                field_name="conversation_ids",
            )
            or [],
        )

    async def _get_latest_session_messages(
        self, args: dict[str, Any]
    ) -> dict[str, Any]:
        limit_per_session = self._as_int(
            args.get("limit_per_session", 1),
            field_name="limit_per_session",
            minimum=1,
        )
        if limit_per_session > 5:
            raise SelfManagementToolInputError(
                "`limit_per_session` must be less than or equal to 5."
            )
        wait_up_to_seconds = self._as_int(
            args.get("wait_up_to_seconds", 0),
            field_name="wait_up_to_seconds",
            minimum=0,
        )
        if wait_up_to_seconds > 20:
            raise SelfManagementToolInputError(
                "`wait_up_to_seconds` must be less than or equal to 20."
            )
        poll_interval_seconds = self._as_int(
            args.get("poll_interval_seconds", 1),
            field_name="poll_interval_seconds",
            minimum=1,
        )
        if poll_interval_seconds > 5:
            raise SelfManagementToolInputError(
                "`poll_interval_seconds` must be less than or equal to 5."
            )
        payload = await self_management_sessions_service.get_latest_messages(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_ids=self._as_str_list(
                args.get("conversation_ids"),
                field_name="conversation_ids",
            ),
            limit_per_session=limit_per_session,
            after_agent_message_id_by_conversation=self._as_optional_str_dict(
                args.get("after_agent_message_id_by_conversation"),
                field_name="after_agent_message_id_by_conversation",
            ),
            wait_up_to_seconds=wait_up_to_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        return {
            "summary": payload["summary"],
            "items": [
                self._serialize_latest_session_messages_item(item)
                for item in payload["items"]
            ],
        }

    async def _update_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session_item = await self_management_sessions_service.update_session(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_id=self._as_str(
                args.get("conversation_id"),
                field_name="conversation_id",
            ),
            title=self._as_str(args.get("title"), field_name="title"),
        )
        return {"session": self._serialize_session(session_item)}

    async def _archive_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session_item = await self_management_sessions_service.archive_session(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_id=self._as_str(
                args.get("conversation_id"),
                field_name="conversation_id",
            ),
        )
        return {"session": self._serialize_session(session_item)}

    async def _unarchive_session(self, args: dict[str, Any]) -> dict[str, Any]:
        session_item = await self_management_sessions_service.unarchive_session(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_id=self._as_str(
                args.get("conversation_id"),
                field_name="conversation_id",
            ),
        )
        return {"session": self._serialize_session(session_item)}

    async def _send_session_message(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self_management_delegated_conversation_service.send_messages_to_sessions(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            conversation_ids=self._as_uuid_list(
                args.get("conversation_ids"),
                field_name="conversation_ids",
            ),
            message=self._as_str(args.get("message"), field_name="message"),
        )

    async def _list_agents(self, args: dict[str, Any]) -> dict[str, Any]:
        page = self._as_int(args.get("page", 1), field_name="page", minimum=1)
        size = self._as_int(args.get("size", 20), field_name="size", minimum=1)
        health_bucket = self._as_optional_str(args.get("health_bucket")) or "all"
        items, total, counts = await self_management_agents_service.list_agents(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            page=page,
            size=size,
            health_bucket=health_bucket,
        )
        pages = (total + size - 1) // size if size else 0
        return {
            "items": [self._serialize_agent(item) for item in items],
            "pagination": {
                "page": page,
                "size": size,
                "total": total,
                "pages": pages,
            },
            "meta": {
                "counts": {
                    "healthy": counts.healthy,
                    "degraded": counts.degraded,
                    "unavailable": counts.unavailable,
                    "unknown": counts.unknown,
                }
            },
        }

    async def _get_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        record = await self_management_agents_service.get_agent(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_id=self._as_uuid(args.get("agent_id"), field_name="agent_id"),
        )
        return {"agent": self._serialize_agent(record)}

    async def _check_agent_health(self, args: dict[str, Any]) -> dict[str, Any]:
        force = (
            cast(bool, self._as_optional_bool(args.get("force"), field_name="force"))
            if args.get("force") is not None
            else True
        )
        summary, items = await self_management_agents_service.check_agent_health(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_id=self._as_uuid(args.get("agent_id"), field_name="agent_id"),
            force=force,
        )
        return self._serialize_agent_health_check(summary=summary, items=items)

    async def _check_all_agents_health(self, args: dict[str, Any]) -> dict[str, Any]:
        force = (
            cast(bool, self._as_optional_bool(args.get("force"), field_name="force"))
            if args.get("force") is not None
            else False
        )
        summary, items = await self_management_agents_service.check_all_agents_health(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            force=force,
        )
        return self._serialize_agent_health_check(summary=summary, items=items)

    async def _create_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        enabled = (
            cast(
                bool,
                self._as_optional_bool(args.get("enabled"), field_name="enabled"),
            )
            if args.get("enabled") is not None
            else True
        )
        record = await self_management_agents_service.create_agent(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            name=self._as_str(args.get("name"), field_name="name"),
            card_url=self._as_str(args.get("card_url"), field_name="card_url"),
            auth_type=self._as_str(args.get("auth_type"), field_name="auth_type"),
            auth_header=self._as_optional_str(args.get("auth_header")),
            auth_scheme=self._as_optional_str(args.get("auth_scheme")),
            enabled=enabled,
            tags=self._as_optional_str_list(args.get("tags"), field_name="tags"),
            extra_headers=self._as_optional_str_dict(
                args.get("extra_headers"),
                field_name="extra_headers",
            ),
            invoke_metadata_defaults=self._as_optional_str_dict(
                args.get("invoke_metadata_defaults"),
                field_name="invoke_metadata_defaults",
            ),
            token=self._as_optional_str(args.get("token")),
            basic_username=self._as_optional_str(args.get("basic_username")),
            basic_password=self._as_optional_str(args.get("basic_password")),
        )
        return {"agent": self._serialize_agent(record)}

    async def _update_agent_config(self, args: dict[str, Any]) -> dict[str, Any]:
        record = await self_management_agents_service.update_config(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_id=self._as_uuid(args.get("agent_id"), field_name="agent_id"),
            name=self._as_optional_str(args.get("name")),
            card_url=self._as_optional_str(args.get("card_url")),
            auth_type=self._as_optional_str(args.get("auth_type")),
            auth_header=self._as_optional_str(args.get("auth_header")),
            auth_scheme=self._as_optional_str(args.get("auth_scheme")),
            enabled=self._as_optional_bool(args.get("enabled"), field_name="enabled"),
            tags=self._as_optional_str_list(args.get("tags"), field_name="tags"),
            extra_headers=self._as_optional_str_dict(
                args.get("extra_headers"),
                field_name="extra_headers",
            ),
            invoke_metadata_defaults=self._as_optional_str_dict(
                args.get("invoke_metadata_defaults"),
                field_name="invoke_metadata_defaults",
            ),
            token=self._as_optional_str(args.get("token")),
            basic_username=self._as_optional_str(args.get("basic_username")),
            basic_password=self._as_optional_str(args.get("basic_password")),
        )
        return {"agent": self._serialize_agent(record)}

    async def _delete_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = self._as_uuid(args.get("agent_id"), field_name="agent_id")
        await self_management_agents_service.delete_agent(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_id=agent_id,
        )
        return {"agent_id": str(agent_id), "deleted": True}

    async def _start_agent_sessions(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self_management_delegated_conversation_service.start_sessions_for_agents(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_ids=self._as_uuid_list(args.get("agent_ids"), field_name="agent_ids"),
            message=self._as_str(args.get("message"), field_name="message"),
        )

    def _timezone_str(self) -> str:
        return cast(str, self.current_user.timezone or "UTC")

    @staticmethod
    def _as_int(value: Any, *, field_name: str, minimum: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError) as exc:
            raise SelfManagementToolInputError(
                f"`{field_name}` must be an integer."
            ) from exc
        if resolved < minimum:
            raise SelfManagementToolInputError(f"`{field_name}` must be >= {minimum}.")
        return resolved

    @staticmethod
    def _as_str(value: Any, *, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SelfManagementToolInputError(
                f"`{field_name}` is required and must be a non-empty string."
            )
        return value

    @staticmethod
    def _as_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise SelfManagementToolInputError("Expected a string value.")
        return value

    @staticmethod
    def _as_uuid(value: Any, *, field_name: str) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str) or not value.strip():
            raise SelfManagementToolInputError(
                f"`{field_name}` is required and must be a UUID string."
            )
        try:
            return UUID(value)
        except (TypeError, ValueError) as exc:
            raise SelfManagementToolInputError(
                f"`{field_name}` must be a valid UUID."
            ) from exc

    def _as_optional_uuid(self, value: Any, *, field_name: str) -> UUID | None:
        if value is None:
            return None
        return self._as_uuid(value, field_name=field_name)

    def _as_uuid_list(self, value: Any, *, field_name: str) -> list[UUID]:
        raw_values = self._as_optional_str_list(value, field_name=field_name)
        if not raw_values:
            raise SelfManagementToolInputError(
                f"`{field_name}` must contain at least one UUID string."
            )
        return [self._as_uuid(item, field_name=field_name) for item in raw_values]

    def _as_str_list(self, value: Any, *, field_name: str) -> list[str]:
        raw_values = self._as_optional_str_list(value, field_name=field_name)
        if not raw_values:
            raise SelfManagementToolInputError(
                f"`{field_name}` must contain at least one string."
            )
        if any(not item.strip() for item in raw_values):
            raise SelfManagementToolInputError(
                f"`{field_name}` must contain only non-empty strings."
            )
        return raw_values

    @staticmethod
    def _as_optional_bool(value: Any, *, field_name: str) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        raise SelfManagementToolInputError(f"`{field_name}` must be a boolean.")

    @staticmethod
    def _as_optional_dict(
        value: Any,
        *,
        field_name: str,
    ) -> dict[str, object] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise SelfManagementToolInputError(f"`{field_name}` must be an object.")
        return cast(dict[str, object], value)

    @staticmethod
    def _as_optional_str_dict(
        value: Any,
        *,
        field_name: str,
    ) -> dict[str, str] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise SelfManagementToolInputError(f"`{field_name}` must be an object.")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise SelfManagementToolInputError(
                    f"`{field_name}` must contain only string keys and string values."
                )
            normalized[key] = item
        return normalized

    @staticmethod
    def _as_optional_str_list(
        value: Any,
        *,
        field_name: str,
    ) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise SelfManagementToolInputError(f"`{field_name}` must be an array.")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise SelfManagementToolInputError(
                    f"`{field_name}` must contain only strings."
                )
            normalized.append(item)
        return normalized

    @staticmethod
    def _as_session_source(value: str | None) -> SessionSource | None:
        if value is None:
            return None
        if value in {"manual", "scheduled"}:
            return cast(SessionSource, value)
        raise SelfManagementToolInputError(
            "`source` must be one of: manual, scheduled."
        )

    @staticmethod
    def _as_session_status(value: str) -> str:
        if value in {"active", "archived", "all"}:
            return value
        raise SelfManagementToolInputError(
            "`status` must be one of: active, archived, all."
        )

    @staticmethod
    def _serialize_job(task: A2AScheduleTask, *, timezone_str: str) -> dict[str, Any]:
        return {
            "id": str(cast(UUID | None, task.id)),
            "name": task.name,
            "agent_id": str(task.agent_id),
            "conversation_id": (
                str(task.conversation_id) if task.conversation_id is not None else None
            ),
            "conversation_policy": task.conversation_policy,
            "prompt": task.prompt,
            "cycle_type": task.cycle_type,
            "time_point": dict(task.time_point or {}),
            "schedule_timezone": timezone_str,
            "enabled": bool(task.enabled),
            "next_run_at_utc": (
                task.next_run_at.isoformat() if task.next_run_at is not None else None
            ),
            "last_run_at": (
                task.last_run_at.isoformat() if task.last_run_at is not None else None
            ),
            "last_run_status": task.last_run_status,
            "consecutive_failures": int(task.consecutive_failures or 0),
            "updated_at": (
                task.updated_at.isoformat() if task.updated_at is not None else None
            ),
        }

    @staticmethod
    def _serialize_session(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": str(item["conversationId"]),
            "source": item.get("source"),
            "external_provider": item.get("external_provider"),
            "external_session_id": item.get("external_session_id"),
            "agent_id": (
                str(item["agent_id"]) if item.get("agent_id") is not None else None
            ),
            "agent_source": item.get("agent_source"),
            "title": item.get("title"),
            "status": item.get("status"),
            "last_active_at": (
                item["last_active_at"].isoformat()
                if item.get("last_active_at") is not None
                else None
            ),
            "created_at": (
                item["created_at"].isoformat()
                if item.get("created_at") is not None
                else None
            ),
        }

    @classmethod
    def _serialize_latest_session_messages_item(
        cls, item: dict[str, Any]
    ) -> dict[str, Any]:
        serialized = {
            "conversation_id": str(item["conversation_id"]),
            "status": item.get("status"),
        }
        if item.get("observation_status") is not None:
            serialized["observation_status"] = item.get("observation_status")
        if item.get("after_agent_message_id") is not None:
            serialized["after_agent_message_id"] = item.get("after_agent_message_id")
        if item.get("latest_agent_message_id") is not None:
            serialized["latest_agent_message_id"] = item.get("latest_agent_message_id")
        if item.get("session") is not None:
            serialized["session"] = cls._serialize_session(
                cast(dict[str, Any], item["session"])
            )
        if item.get("messages") is not None:
            serialized["messages"] = [
                {
                    "message_id": str(message["message_id"]),
                    "role": message.get("role"),
                    "content": message.get("content"),
                    "created_at": (
                        message["created_at"].isoformat()
                        if message.get("created_at") is not None
                        else None
                    ),
                    "status": message.get("status"),
                }
                for message in cast(list[dict[str, Any]], item["messages"])
            ]
        if item.get("error") is not None:
            serialized["error"] = item.get("error")
        if item.get("error_code") is not None:
            serialized["error_code"] = item.get("error_code")
        return serialized

    @staticmethod
    def _serialize_agent(record: A2AAgentRecord) -> dict[str, Any]:
        return {
            "id": str(record.id),
            "name": record.name,
            "card_url": record.card_url,
            "auth_type": record.auth_type,
            "auth_header": record.auth_header,
            "auth_scheme": record.auth_scheme,
            "enabled": record.enabled,
            "health_status": record.health_status,
            "consecutive_health_check_failures": record.consecutive_health_check_failures,
            "last_health_check_at": (
                record.last_health_check_at.isoformat()
                if record.last_health_check_at is not None
                else None
            ),
            "last_successful_health_check_at": (
                record.last_successful_health_check_at.isoformat()
                if record.last_successful_health_check_at is not None
                else None
            ),
            "last_health_check_error": record.last_health_check_error,
            "last_health_check_reason_code": record.last_health_check_reason_code,
            "tags": list(record.tags),
            "extra_headers": dict(record.extra_headers),
            "invoke_metadata_defaults": dict(record.invoke_metadata_defaults),
            "token_last4": record.token_last4,
            "username_hint": record.username_hint,
            "created_at": str(record.created_at),
            "updated_at": str(record.updated_at),
        }

    @staticmethod
    def _serialize_agent_health_check(
        *, summary: Any, items: list[Any]
    ) -> dict[str, Any]:
        return {
            "summary": {
                "requested": int(summary.requested),
                "checked": int(summary.checked),
                "skipped_cooldown": int(summary.skipped_cooldown),
                "healthy": int(summary.healthy),
                "degraded": int(summary.degraded),
                "unavailable": int(summary.unavailable),
                "unknown": int(summary.unknown),
            },
            "items": [
                {
                    "agent_id": str(item.agent_id),
                    "health_status": item.health_status,
                    "checked_at": item.checked_at.isoformat(),
                    "skipped_cooldown": bool(item.skipped_cooldown),
                    "error": item.error,
                    "reason_code": item.reason_code,
                }
                for item in items
            ],
        }


__all__ = [
    "SelfManagementToolExecutionResult",
    "SelfManagementToolInputError",
    "SelfManagementToolkit",
]
