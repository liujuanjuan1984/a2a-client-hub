"""Minimal self-management CLI for authenticated users."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import (
    clear_actor_context,
    clear_user_context,
    reset_actor_context,
    reset_user_context,
    set_actor_context,
    set_user_context,
)
from app.core.security import create_user_access_token, verify_access_token
from app.db.models.user import User
from app.db.session import AsyncSessionLocal
from app.features.agents_shared.actor_context import (
    SelfManagementActorType,
    build_self_management_actor_context,
)
from app.features.agents_shared.capability_catalog import (
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
)
from app.features.agents_shared.self_management_toolkit import SelfManagementToolkit
from app.features.agents_shared.tool_gateway import (
    SelfManagementConfirmationPolicy,
    SelfManagementSurface,
    SelfManagementToolGateway,
)
from app.features.auth.service import (
    InvalidCredentialsError,
    UserLockedError,
    UserNotFoundError,
    authenticate_user,
    get_active_user,
)

_CLI_SESSION_FILE_ENV = "A2A_CLIENT_HUB_CLI_SESSION_FILE"


@dataclass(frozen=True)
class CliSessionState:
    """Persisted authenticated CLI session."""

    access_token: str
    user_id: str
    email: str
    name: str
    token_type: str = "bearer"


class CliCommandError(Exception):
    """Base exception for handled CLI failures."""

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _default_session_file() -> Path:
    return Path.home() / ".config" / "a2a-client-hub" / "cli-session.json"


def _session_file() -> Path:
    configured = os.getenv(_CLI_SESSION_FILE_ENV)
    if configured:
        return Path(configured).expanduser()
    return _default_session_file()


def _write_session(state: CliSessionState) -> Path:
    session_file = _session_file()
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_text(
        json.dumps(asdict(state), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(session_file, 0o600)
    return session_file


def _load_session() -> CliSessionState:
    session_file = _session_file()
    if not session_file.exists():
        raise CliCommandError(
            "No active CLI session. Run `a2a-client-hub login` first.",
        )

    payload = json.loads(session_file.read_text(encoding="utf-8"))
    try:
        return CliSessionState(**payload)
    except TypeError as exc:
        raise CliCommandError(
            "Saved CLI session is invalid. Run `a2a-client-hub login` again.",
        ) from exc


def _clear_session() -> bool:
    session_file = _session_file()
    if not session_file.exists():
        return False
    session_file.unlink()
    return True


def _print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
    sys.stdout.write("\n")


def _serialize_user(user: User) -> dict[str, Any]:
    user_id = cast(UUID | None, user.id)
    return {
        "id": str(user_id) if user_id is not None else None,
        "email": cast(str, user.email),
        "name": cast(str, user.name),
        "is_superuser": bool(user.is_superuser),
        "timezone": cast(str, user.timezone or "UTC"),
    }


def _parse_time_point(raw: str | None) -> dict[str, object] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliCommandError(
            "`--time-point-json` must be valid JSON object text.",
        ) from exc
    if not isinstance(parsed, dict):
        raise CliCommandError("`--time-point-json` must decode to a JSON object.")
    return cast(dict[str, object], parsed)


def _parse_json_object(
    *,
    raw: str | None,
    option_name: str,
) -> dict[str, str] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliCommandError(
            f"`{option_name}` must be valid JSON object text."
        ) from exc
    if not isinstance(parsed, dict):
        raise CliCommandError(f"`{option_name}` must decode to a JSON object.")
    normalized: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise CliCommandError(
                f"`{option_name}` must contain only string keys and string values."
            )
        normalized[key] = value
    return normalized


def _parse_json_string_list(
    *,
    raw: str | None,
    option_name: str,
) -> list[str] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliCommandError(
            f"`{option_name}` must be valid JSON array text."
        ) from exc
    if not isinstance(parsed, list):
        raise CliCommandError(f"`{option_name}` must decode to a JSON array.")
    normalized: list[str] = []
    for item in parsed:
        if not isinstance(item, str):
            raise CliCommandError(f"`{option_name}` must contain only strings.")
        normalized.append(item)
    return normalized


def _parse_optional_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise CliCommandError("`--enabled` must be one of true/false/yes/no/1/0/on/off.")


def _require_confirmation(
    *,
    operation_name: str,
    confirmation_policy: SelfManagementConfirmationPolicy,
    confirmed: bool,
) -> None:
    if confirmation_policy == SelfManagementConfirmationPolicy.NONE:
        return
    if confirmed:
        return
    if not sys.stdin.isatty():
        raise CliCommandError(
            f"`{operation_name}` requires explicit confirmation. Re-run with --confirm.",
        )

    answer = input(f"Confirm `{operation_name}` by typing `yes`: ").strip().lower()
    if answer != "yes":
        raise CliCommandError(f"`{operation_name}` cancelled.")


@contextmanager
def _bind_cli_actor_context(user: User) -> Iterator[None]:
    user_id = str(cast(UUID, user.id))
    user_token = set_user_context(user_id)
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_CLI,
    )
    actor_tokens = set_actor_context(
        principal_user_id=str(actor.principal_user_id),
        actor_type=actor.actor_type.value,
        admin_mode=actor.admin_mode,
    )
    try:
        yield
    finally:
        reset_user_context(user_token)
        reset_actor_context(actor_tokens)


async def _build_cli_gateway(
    db: AsyncSession,
) -> tuple[CliSessionState, User, SelfManagementToolGateway]:
    session_state = _load_session()
    user_id = verify_access_token(session_state.access_token)
    if user_id is None:
        raise CliCommandError(
            "Saved CLI session is invalid or expired. "
            "Run `a2a-client-hub login` again.",
        )

    user = await get_active_user(db, user_id=UUID(user_id))
    actor = build_self_management_actor_context(
        user=user,
        actor_type=SelfManagementActorType.HUMAN_CLI,
    )
    return (
        session_state,
        user,
        SelfManagementToolGateway(actor, surface=SelfManagementSurface.CLI),
    )


async def _build_cli_toolkit(
    db: AsyncSession,
) -> tuple[CliSessionState, User, SelfManagementToolkit]:
    session_state, user, gateway = await _build_cli_gateway(db)
    return (
        session_state,
        user,
        SelfManagementToolkit(
            db=db,
            current_user=user,
            gateway=gateway,
        ),
    )


async def _handle_login(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        try:
            user = await authenticate_user(
                db,
                email=cast(str, args.email),
                password=cast(str, args.password),
            )
        except (InvalidCredentialsError, UserLockedError, UserNotFoundError) as exc:
            await db.rollback()
            raise CliCommandError(str(exc)) from exc

        await db.commit()
        await db.refresh(user)

    state = CliSessionState(
        access_token=create_user_access_token(cast(UUID, user.id)),
        user_id=str(cast(UUID, user.id)),
        email=cast(str, user.email),
        name=cast(str, user.name),
    )
    session_file = _write_session(state)
    _print_json(
        {
            "message": "CLI login succeeded.",
            "session_file": str(session_file),
            "user": _serialize_user(user),
        }
    )


async def _handle_logout(_args: argparse.Namespace) -> None:
    removed = _clear_session()
    _print_json(
        {"message": "CLI session cleared." if removed else "No active CLI session."}
    )


async def _handle_whoami(_args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        session_state, user, _gateway = await _build_cli_gateway(db)

    _print_json(
        {
            "session_file": str(_session_file()),
            "token_type": session_state.token_type,
            "user": _serialize_user(user),
        }
    )


async def _handle_jobs_list(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_LIST.operation_id,
                arguments={
                    "page": cast(int, args.page),
                    "size": cast(int, args.size),
                },
            )
    _print_json(result.payload)


async def _handle_jobs_get(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_GET.operation_id,
                arguments={"task_id": cast(str, args.task_id)},
            )
    _print_json(result.payload)


async def _handle_jobs_pause(args: argparse.Namespace) -> None:
    _require_confirmation(
        operation_name=SELF_JOBS_PAUSE.command_name or SELF_JOBS_PAUSE.operation_id,
        confirmation_policy=SELF_JOBS_PAUSE.confirmation_policy,
        confirmed=bool(args.confirm),
    )
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_PAUSE.operation_id,
                arguments={"task_id": cast(str, args.task_id)},
            )
    _print_json(result.payload)


async def _handle_sessions_list(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_SESSIONS_LIST.operation_id,
                arguments={
                    "page": cast(int, args.page),
                    "size": cast(int, args.size),
                    "source": cast(str | None, args.source),
                    "agent_id": cast(str | None, args.agent_id),
                },
            )
    _print_json(result.payload)


async def _handle_sessions_get(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_SESSIONS_GET.operation_id,
                arguments={
                    "conversation_id": cast(str, args.conversation_id),
                },
            )
    _print_json(result.payload)


async def _handle_agents_list(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_AGENTS_LIST.operation_id,
                arguments={
                    "page": cast(int, args.page),
                    "size": cast(int, args.size),
                    "health_bucket": cast(str, args.health_bucket),
                },
            )
    _print_json(result.payload)


async def _handle_agents_get(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_AGENTS_GET.operation_id,
                arguments={"agent_id": cast(str, args.agent_id)},
            )
    _print_json(result.payload)


async def _handle_agents_update_config(args: argparse.Namespace) -> None:
    _require_confirmation(
        operation_name=(
            SELF_AGENTS_UPDATE_CONFIG.command_name
            or SELF_AGENTS_UPDATE_CONFIG.operation_id
        ),
        confirmation_policy=SELF_AGENTS_UPDATE_CONFIG.confirmation_policy,
        confirmed=bool(args.confirm),
    )
    name = cast(str | None, args.name)
    enabled = _parse_optional_bool(cast(str | None, args.enabled))
    tags = _parse_json_string_list(
        raw=cast(str | None, args.tags_json), option_name="--tags-json"
    )
    extra_headers = _parse_json_object(
        raw=cast(str | None, args.extra_headers_json),
        option_name="--extra-headers-json",
    )
    invoke_metadata_defaults = _parse_json_object(
        raw=cast(str | None, args.invoke_metadata_defaults_json),
        option_name="--invoke-metadata-defaults-json",
    )
    if (
        name is None
        and enabled is None
        and tags is None
        and extra_headers is None
        and invoke_metadata_defaults is None
    ):
        raise CliCommandError(
            "`agents update-config` requires at least one supported config field to change.",
        )
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_AGENTS_UPDATE_CONFIG.operation_id,
                arguments={
                    "agent_id": cast(str, args.agent_id),
                    "name": name,
                    "enabled": enabled,
                    "tags": tags,
                    "extra_headers": extra_headers,
                    "invoke_metadata_defaults": invoke_metadata_defaults,
                },
            )
    _print_json(result.payload)


async def _handle_jobs_resume(args: argparse.Namespace) -> None:
    _require_confirmation(
        operation_name=SELF_JOBS_RESUME.command_name or SELF_JOBS_RESUME.operation_id,
        confirmation_policy=SELF_JOBS_RESUME.confirmation_policy,
        confirmed=bool(args.confirm),
    )
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_RESUME.operation_id,
                arguments={"task_id": cast(str, args.task_id)},
            )
    _print_json(result.payload)


async def _handle_jobs_update_prompt(args: argparse.Namespace) -> None:
    _require_confirmation(
        operation_name=(
            SELF_JOBS_UPDATE_PROMPT.command_name or SELF_JOBS_UPDATE_PROMPT.operation_id
        ),
        confirmation_policy=SELF_JOBS_UPDATE_PROMPT.confirmation_policy,
        confirmed=bool(args.confirm),
    )
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_UPDATE_PROMPT.operation_id,
                arguments={
                    "task_id": cast(str, args.task_id),
                    "prompt": cast(str, args.prompt),
                },
            )
    _print_json(result.payload)


async def _handle_jobs_update_schedule(args: argparse.Namespace) -> None:
    _require_confirmation(
        operation_name=(
            SELF_JOBS_UPDATE_SCHEDULE.command_name
            or SELF_JOBS_UPDATE_SCHEDULE.operation_id
        ),
        confirmation_policy=SELF_JOBS_UPDATE_SCHEDULE.confirmation_policy,
        confirmed=bool(args.confirm),
    )
    cycle_type = cast(str | None, args.cycle_type)
    schedule_timezone = cast(str | None, args.schedule_timezone)
    time_point = _parse_time_point(cast(str | None, args.time_point_json))
    if cycle_type is None and time_point is None and schedule_timezone is None:
        raise CliCommandError(
            "`jobs update-schedule` requires at least one schedule field to change.",
        )
    async with AsyncSessionLocal() as db:
        _, user, toolkit = await _build_cli_toolkit(db)
        with _bind_cli_actor_context(user):
            result = await toolkit.execute(
                operation_id=SELF_JOBS_UPDATE_SCHEDULE.operation_id,
                arguments={
                    "task_id": cast(str, args.task_id),
                    "cycle_type": cycle_type,
                    "time_point": time_point,
                    "schedule_timezone": schedule_timezone,
                },
            )
    _print_json(result.payload)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="a2a-client-hub",
        description="Authenticated CLI for self-management operations.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Authenticate a user.")
    login_parser.add_argument("--email", required=True)
    login_parser.add_argument("--password", required=True)

    subparsers.add_parser("logout", help="Clear the saved CLI session.")
    subparsers.add_parser("whoami", help="Show the authenticated CLI user.")

    jobs_parser = subparsers.add_parser("jobs", help="Manage current-user jobs.")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command", required=True)

    jobs_list_parser = jobs_subparsers.add_parser("list", help="List jobs.")
    jobs_list_parser.add_argument("--page", type=int, default=1)
    jobs_list_parser.add_argument("--size", type=int, default=20)

    jobs_get_parser = jobs_subparsers.add_parser("get", help="Read one job.")
    jobs_get_parser.add_argument("task_id")

    jobs_pause_parser = jobs_subparsers.add_parser("pause", help="Pause one job.")
    jobs_pause_parser.add_argument("task_id")
    jobs_pause_parser.add_argument("--confirm", action="store_true")

    jobs_resume_parser = jobs_subparsers.add_parser("resume", help="Resume one job.")
    jobs_resume_parser.add_argument("task_id")
    jobs_resume_parser.add_argument("--confirm", action="store_true")

    jobs_update_prompt_parser = jobs_subparsers.add_parser(
        "update-prompt",
        help="Update the prompt for one job.",
    )
    jobs_update_prompt_parser.add_argument("task_id")
    jobs_update_prompt_parser.add_argument("--prompt", required=True)
    jobs_update_prompt_parser.add_argument("--confirm", action="store_true")

    jobs_update_schedule_parser = jobs_subparsers.add_parser(
        "update-schedule",
        help="Update schedule fields for one job.",
    )
    jobs_update_schedule_parser.add_argument("task_id")
    jobs_update_schedule_parser.add_argument("--cycle-type")
    jobs_update_schedule_parser.add_argument("--time-point-json")
    jobs_update_schedule_parser.add_argument("--schedule-timezone")
    jobs_update_schedule_parser.add_argument("--confirm", action="store_true")

    sessions_parser = subparsers.add_parser(
        "sessions", help="Manage current-user sessions."
    )
    sessions_subparsers = sessions_parser.add_subparsers(
        dest="sessions_command",
        required=True,
    )

    sessions_list_parser = sessions_subparsers.add_parser(
        "list",
        help="List sessions.",
    )
    sessions_list_parser.add_argument("--page", type=int, default=1)
    sessions_list_parser.add_argument("--size", type=int, default=20)
    sessions_list_parser.add_argument("--source", choices=["manual", "scheduled"])
    sessions_list_parser.add_argument("--agent-id")

    sessions_get_parser = sessions_subparsers.add_parser(
        "get",
        help="Read one session.",
    )
    sessions_get_parser.add_argument("conversation_id")

    agents_parser = subparsers.add_parser("agents", help="Manage current-user agents.")
    agents_subparsers = agents_parser.add_subparsers(
        dest="agents_command",
        required=True,
    )

    agents_list_parser = agents_subparsers.add_parser("list", help="List agents.")
    agents_list_parser.add_argument("--page", type=int, default=1)
    agents_list_parser.add_argument("--size", type=int, default=20)
    agents_list_parser.add_argument(
        "--health-bucket",
        choices=["all", "healthy", "degraded", "unavailable", "unknown", "attention"],
        default="all",
    )

    agents_get_parser = agents_subparsers.add_parser("get", help="Read one agent.")
    agents_get_parser.add_argument("agent_id")

    agents_update_parser = agents_subparsers.add_parser(
        "update-config",
        help="Update a constrained subset of one agent config.",
    )
    agents_update_parser.add_argument("agent_id")
    agents_update_parser.add_argument("--name")
    agents_update_parser.add_argument("--enabled")
    agents_update_parser.add_argument("--tags-json")
    agents_update_parser.add_argument("--extra-headers-json")
    agents_update_parser.add_argument("--invoke-metadata-defaults-json")
    agents_update_parser.add_argument("--confirm", action="store_true")

    return parser


async def run_cli(argv: Sequence[str] | None = None) -> int:
    """Run the CLI using the provided argument vector."""

    clear_user_context()
    clear_actor_context()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        command = cast(str, args.command)
        if command == "login":
            await _handle_login(args)
            return 0
        if command == "logout":
            await _handle_logout(args)
            return 0
        if command == "whoami":
            await _handle_whoami(args)
            return 0
        if command == "jobs":
            jobs_command = cast(str, args.jobs_command)
            if jobs_command == "list":
                await _handle_jobs_list(args)
                return 0
            if jobs_command == "get":
                await _handle_jobs_get(args)
                return 0
            if jobs_command == "pause":
                await _handle_jobs_pause(args)
                return 0
            if jobs_command == "resume":
                await _handle_jobs_resume(args)
                return 0
            if jobs_command == "update-prompt":
                await _handle_jobs_update_prompt(args)
                return 0
            if jobs_command == "update-schedule":
                await _handle_jobs_update_schedule(args)
                return 0
        if command == "sessions":
            sessions_command = cast(str, args.sessions_command)
            if sessions_command == "list":
                await _handle_sessions_list(args)
                return 0
            if sessions_command == "get":
                await _handle_sessions_get(args)
                return 0
        if command == "agents":
            agents_command = cast(str, args.agents_command)
            if agents_command == "list":
                await _handle_agents_list(args)
                return 0
            if agents_command == "get":
                await _handle_agents_get(args)
                return 0
            if agents_command == "update-config":
                await _handle_agents_update_config(args)
                return 0
    except CliCommandError as exc:
        sys.stderr.write(f"{exc}\n")
        return exc.exit_code
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    sys.stderr.write("Unknown command.\n")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint used by the console script."""

    return asyncio.run(run_cli(argv))


if __name__ == "__main__":
    raise SystemExit(main())
