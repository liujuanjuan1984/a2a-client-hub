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
    SELF_AGENTS_GET,
    SELF_AGENTS_LIST,
    SELF_AGENTS_UPDATE_CONFIG,
    SELF_JOBS_GET,
    SELF_JOBS_LIST,
    SELF_JOBS_PAUSE,
    SELF_JOBS_RESUME,
    SELF_JOBS_UPDATE_PROMPT,
    SELF_JOBS_UPDATE_SCHEDULE,
    SELF_SESSIONS_GET,
    SELF_SESSIONS_LIST,
    get_self_management_operation,
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
        elif operation.operation_id == SELF_JOBS_PAUSE.operation_id:
            payload = await self._pause_job(args)
        elif operation.operation_id == SELF_JOBS_RESUME.operation_id:
            payload = await self._resume_job(args)
        elif operation.operation_id == SELF_JOBS_UPDATE_PROMPT.operation_id:
            payload = await self._update_job_prompt(args)
        elif operation.operation_id == SELF_JOBS_UPDATE_SCHEDULE.operation_id:
            payload = await self._update_job_schedule(args)
        elif operation.operation_id == SELF_SESSIONS_LIST.operation_id:
            payload = await self._list_sessions(args)
        elif operation.operation_id == SELF_SESSIONS_GET.operation_id:
            payload = await self._get_session(args)
        elif operation.operation_id == SELF_AGENTS_LIST.operation_id:
            payload = await self._list_agents(args)
        elif operation.operation_id == SELF_AGENTS_GET.operation_id:
            payload = await self._get_agent(args)
        elif operation.operation_id == SELF_AGENTS_UPDATE_CONFIG.operation_id:
            payload = await self._update_agent_config(args)
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

    async def _list_sessions(self, args: dict[str, Any]) -> dict[str, Any]:
        page = self._as_int(args.get("page", 1), field_name="page", minimum=1)
        size = self._as_int(args.get("size", 20), field_name="size", minimum=1)
        raw_source = self._as_optional_str(args.get("source"))
        source = self._as_session_source(raw_source)
        agent_id = self._as_optional_uuid(args.get("agent_id"), field_name="agent_id")
        items, extra, _db_mutated = (
            await self_management_sessions_service.list_sessions(
                db=self.db,
                gateway=self.gateway,
                current_user=self.current_user,
                page=page,
                size=size,
                source=source,
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

    async def _update_agent_config(self, args: dict[str, Any]) -> dict[str, Any]:
        record = await self_management_agents_service.update_config(
            db=self.db,
            gateway=self.gateway,
            current_user=self.current_user,
            agent_id=self._as_uuid(args.get("agent_id"), field_name="agent_id"),
            name=self._as_optional_str(args.get("name")),
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
        )
        return {"agent": self._serialize_agent(record)}

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
            "tags": list(record.tags),
            "extra_headers": dict(record.extra_headers),
            "invoke_metadata_defaults": dict(record.invoke_metadata_defaults),
            "token_last4": record.token_last4,
            "username_hint": record.username_hint,
            "created_at": str(record.created_at),
            "updated_at": str(record.updated_at),
        }


__all__ = [
    "SelfManagementToolExecutionResult",
    "SelfManagementToolInputError",
    "SelfManagementToolkit",
]
