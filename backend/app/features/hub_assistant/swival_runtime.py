"""Swival runtime/session helpers for the Hub Assistant."""

from __future__ import annotations

import asyncio
import copy
import importlib
import shutil
import sys
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_hub_assistant_access_token,
    create_hub_assistant_interrupt_token,
)
from app.features.hub_access.actor_context import HubAction
from app.features.hub_access.capability_catalog import list_hub_operation_ids
from app.features.hub_access.operation_gateway import (
    HubConfirmationPolicy,
    HubSurface,
)
from app.features.hub_assistant.models import (
    ConversationRuntimeState,
    HubAssistantPermissionInterrupt,
    HubAssistantUnavailableError,
)
from app.features.hub_assistant.shared.hub_assistant_mcp import (
    HUB_ASSISTANT_MCP_READONLY_MOUNT_PATH,
    HUB_ASSISTANT_MCP_WRITE_MOUNT_PATH,
    list_hub_assistant_mcp_tool_definitions,
)
from app.features.hub_assistant.shared.hub_assistant_tool_contract import (
    HubAssistantToolDefinition,
)

DEFAULT_SYSTEM_PROMPT = (
    "You are the Hub Assistant for a2a-client-hub. Help the authenticated user "
    "inspect or manage their own agents, scheduled jobs, "
    "sessions, and related resources using the provided MCP tools. Never invent "
    "resource ids. For write operations, explain the intended change briefly "
    "before using the tool. If the request is missing required identifiers, ask "
    "one concise follow-up question. When you use `hub_assistant.agents.start_sessions` "
    "or `hub_assistant.sessions.send_message`, treat them as handoff operations: once a "
    "handoff is accepted, do not invent downstream outcomes, and explain that "
    "the request was handed off to the target conversation. You do not need to "
    "wait inline for the target side's live transport or final reply; when new "
    "persisted text results arrive later, the host will resume you so you can "
    "read and continue processing those results."
)
WRITE_APPROVAL_SENTINEL = "[[HUB_ASSISTANT_WRITE_APPROVAL_REQUIRED]]"
WRITE_APPROVAL_OPERATIONS_PREFIX = "[[HUB_ASSISTANT_WRITE_OPERATIONS:"
WRITE_APPROVAL_OPERATIONS_SUFFIX = "]]"
WEB_AGENT_WRITE_OPERATION_IDS = list_hub_operation_ids(
    surface=HubSurface.WEB_AGENT,
    confirmation_policy=HubConfirmationPolicy.REQUIRED,
    action=HubAction.WRITE,
    require_tool_name=True,
)
READ_ONLY_APPENDIX = (
    " This run is read-only. Do not attempt write operations. If the user's latest "
    "request would require a write tool, explain the intended change briefly, do not "
    "claim that any change was applied, append a final line containing exactly "
    f"{WRITE_APPROVAL_SENTINEL}, then append one more final line containing exactly "
    "`[[HUB_ASSISTANT_WRITE_OPERATIONS:<comma-separated operation ids>]]` using "
    "only the required write operation ids from this catalog: "
    + ", ".join(WEB_AGENT_WRITE_OPERATION_IDS)
    + "."
)
WRITE_ENABLED_APPENDIX = (
    " This run includes explicitly approved write tools. Only perform a write when "
    "the user's latest request clearly asks for that change. When additional write "
    "operations outside the approved tool set are needed, do not claim that any "
    "change was applied, append the approval sentinel, and append the exact "
    "operation ids that still require approval."
)


class Clock(Protocol):
    """Minimal clock interface used by the swival runtime helper."""

    def monotonic(self) -> float: ...


class HubAssistantSwivalRuntime:
    """Owns swival session lifecycle and write-approval parsing."""

    def __init__(
        self,
        *,
        persisted_messages_loader: Callable[..., Awaitable[list[dict[str, str]]]],
        time_module: Clock,
    ) -> None:
        self._persisted_messages_loader = persisted_messages_loader
        self._time = time_module
        self._conversation_registry: dict[tuple[str, str], ConversationRuntimeState] = (
            {}
        )
        self._registry_lock = threading.Lock()

    def delegated_token_ttl_seconds(self) -> int:
        return min(
            settings.jwt_access_token_ttl_seconds,
            settings.hub_assistant_swival_delegated_token_ttl_seconds,
        )

    def delegated_token_refresh_skew_seconds(self) -> int:
        ttl_seconds = self.delegated_token_ttl_seconds()
        return max(5, min(30, ttl_seconds // 10 or 1))

    def runtime_session_needs_refresh(
        self,
        *,
        runtime_state: ConversationRuntimeState,
        delegated_write_operation_ids: frozenset[str],
    ) -> bool:
        if runtime_state.session is None:
            return True
        if runtime_state.delegated_write_operation_ids != delegated_write_operation_ids:
            return True
        expires_at = runtime_state.delegated_token_expires_at_monotonic
        if expires_at <= 0:
            return False
        refresh_cutoff = expires_at - self.delegated_token_refresh_skew_seconds()
        return self._time.monotonic() >= refresh_cutoff

    async def invalidate_runtime_session(
        self,
        runtime_state: ConversationRuntimeState,
    ) -> None:
        session = runtime_state.session
        runtime_state.session = None
        runtime_state.delegated_token_expires_at_monotonic = 0.0
        runtime_state.delegated_write_operation_ids = frozenset()
        runtime_state.last_accessed_monotonic = self._time.monotonic()
        if session is not None:
            await asyncio.to_thread(self.close_swival_session, session)

    def extract_mcp_runtime_error(self, result: Any) -> str | None:
        raw_messages = getattr(result, "messages", None)
        if not isinstance(raw_messages, list):
            return None
        for raw_message in reversed(raw_messages):
            if not isinstance(raw_message, dict):
                continue
            if raw_message.get("role") != "tool":
                continue
            content = raw_message.get("content")
            if not isinstance(content, str):
                continue
            normalized = content.strip()
            if normalized.startswith("error: MCP server "):
                return normalized
        return None

    def is_configured(self) -> bool:
        return self.has_required_runtime_configuration() and self.is_swival_importable()

    def build_mcp_url(self, *, allow_write_tools: bool) -> str:
        base = cast(str, settings.hub_assistant_swival_mcp_base_url).rstrip("/")
        mount_path = (
            HUB_ASSISTANT_MCP_WRITE_MOUNT_PATH
            if allow_write_tools
            else HUB_ASSISTANT_MCP_READONLY_MOUNT_PATH
        )
        return f"{base}{mount_path}/"

    def build_system_prompt(
        self,
        *,
        allow_write_tools: bool,
        delegated_write_operation_ids: frozenset[str] = frozenset(),
    ) -> str:
        if allow_write_tools:
            if delegated_write_operation_ids:
                approved_operations = ", ".join(sorted(delegated_write_operation_ids))
                return (
                    DEFAULT_SYSTEM_PROMPT
                    + WRITE_ENABLED_APPENDIX
                    + f" The currently approved write operations are: {approved_operations}."
                )
            return DEFAULT_SYSTEM_PROMPT + WRITE_ENABLED_APPENDIX
        return DEFAULT_SYSTEM_PROMPT + READ_ONLY_APPENDIX

    def answer_requests_write_approval(self, answer: str | None) -> bool:
        return isinstance(answer, str) and WRITE_APPROVAL_SENTINEL in answer

    def strip_write_approval_metadata(self, answer: str | None) -> str | None:
        if not isinstance(answer, str):
            return answer
        stripped_lines = [
            line.strip()
            for line in answer.splitlines()
            if line.strip()
            and line.strip() != WRITE_APPROVAL_SENTINEL
            and not (
                line.strip().startswith(WRITE_APPROVAL_OPERATIONS_PREFIX)
                and line.strip().endswith(WRITE_APPROVAL_OPERATIONS_SUFFIX)
            )
        ]
        stripped = "\n".join(stripped_lines).strip()
        return stripped or None

    def list_write_tool_definitions(self) -> tuple[HubAssistantToolDefinition, ...]:
        return tuple(
            definition
            for definition in list_hub_assistant_mcp_tool_definitions()
            if definition.confirmation_policy != HubConfirmationPolicy.NONE
        )

    def extract_requested_write_operation_ids(
        self,
        answer: str | None,
    ) -> tuple[str, ...]:
        if not isinstance(answer, str):
            return ()
        allowed_operation_ids = {
            definition.operation_id for definition in self.list_write_tool_definitions()
        }
        requested_operation_ids: list[str] = []
        for raw_line in answer.splitlines():
            line = raw_line.strip()
            if not (
                line.startswith(WRITE_APPROVAL_OPERATIONS_PREFIX)
                and line.endswith(WRITE_APPROVAL_OPERATIONS_SUFFIX)
            ):
                continue
            raw_payload = line.removeprefix(
                WRITE_APPROVAL_OPERATIONS_PREFIX
            ).removesuffix(WRITE_APPROVAL_OPERATIONS_SUFFIX)
            for raw_operation_id in raw_payload.split(","):
                operation_id = raw_operation_id.strip()
                if (
                    operation_id
                    and operation_id in allowed_operation_ids
                    and operation_id not in requested_operation_ids
                ):
                    requested_operation_ids.append(operation_id)
        return tuple(requested_operation_ids)

    def build_permission_interrupt(
        self,
        *,
        current_user: Any,
        conversation_id: str,
        message: str,
        answer: str | None,
        requested_write_operation_ids: tuple[str, ...],
    ) -> HubAssistantPermissionInterrupt:
        write_tool_definitions = tuple(
            definition
            for definition in self.list_write_tool_definitions()
            if definition.operation_id in requested_write_operation_ids
        )
        request_id = create_hub_assistant_interrupt_token(
            cast(Any, current_user.id),
            conversation_id=conversation_id,
            message=message,
            tool_names=tuple(
                definition.tool_name for definition in write_tool_definitions
            ),
            requested_operations=requested_write_operation_ids,
        )
        display_message = self.strip_write_approval_metadata(answer) or (
            "This change requires explicit write approval before the Hub Assistant "
            "can continue."
        )
        return HubAssistantPermissionInterrupt(
            request_id=request_id,
            permission="hub-assistant-write",
            patterns=tuple(
                definition.tool_name for definition in write_tool_definitions
            ),
            display_message=display_message,
        )

    def select_run_tool_definitions(
        self,
        *,
        allow_write_tools: bool,
        delegated_write_operation_ids: frozenset[str] = frozenset(),
    ) -> tuple[HubAssistantToolDefinition, ...]:
        tool_definitions = list_hub_assistant_mcp_tool_definitions()
        if allow_write_tools and not delegated_write_operation_ids:
            return tool_definitions
        allowed_write_operation_ids = (
            delegated_write_operation_ids if allow_write_tools else frozenset()
        )
        return tuple(
            definition
            for definition in tool_definitions
            if definition.confirmation_policy == HubConfirmationPolicy.NONE
            or definition.operation_id in allowed_write_operation_ids
        )

    async def get_conversation_runtime_state(
        self,
        *,
        current_user_id: str,
        conversation_id: str,
    ) -> ConversationRuntimeState:
        await self.cleanup_expired_conversations()
        key = (current_user_id, conversation_id)
        with self._registry_lock:
            runtime_state = self._conversation_registry.get(key)
            if runtime_state is None:
                runtime_state = ConversationRuntimeState(
                    last_accessed_monotonic=self._time.monotonic()
                )
                self._conversation_registry[key] = runtime_state
            return runtime_state

    async def cleanup_expired_conversations(self) -> None:
        cutoff = (
            self._time.monotonic() - settings.hub_assistant_swival_session_ttl_seconds
        )
        expired_sessions: list[Any] = []
        with self._registry_lock:
            expired_keys = [
                key
                for key, runtime_state in self._conversation_registry.items()
                if runtime_state.last_accessed_monotonic
                and runtime_state.last_accessed_monotonic < cutoff
            ]
            for key in expired_keys:
                runtime_state = self._conversation_registry.pop(key)
                if runtime_state.session is not None:
                    expired_sessions.append(runtime_state.session)
        for session in expired_sessions:
            await asyncio.to_thread(self.close_swival_session, session)

    async def ensure_conversation_session(
        self,
        *,
        db: AsyncSession,
        runtime_state: ConversationRuntimeState,
        current_user: Any,
        conversation_id: str,
        delegated_write_operation_ids: frozenset[str],
    ) -> Any:
        if not self.runtime_session_needs_refresh(
            runtime_state=runtime_state,
            delegated_write_operation_ids=delegated_write_operation_ids,
        ):
            runtime_state.last_accessed_monotonic = self._time.monotonic()
            return runtime_state.session

        previous_session = runtime_state.session
        new_session = await asyncio.to_thread(
            self.create_swival_session,
            current_user=current_user,
            conversation_id=conversation_id,
            delegated_write_operation_ids=delegated_write_operation_ids,
        )
        if previous_session is not None:
            await asyncio.to_thread(
                self.transfer_conversation_state, previous_session, new_session
            )
            await asyncio.to_thread(self.close_swival_session, previous_session)
        else:
            await self.best_effort_rehydrate_swival_session(
                db=db,
                current_user=current_user,
                conversation_id=conversation_id,
                session=new_session,
            )

        runtime_state.session = new_session
        runtime_state.delegated_write_operation_ids = delegated_write_operation_ids
        runtime_state.delegated_token_expires_at_monotonic = float(
            getattr(
                new_session,
                "_hub_assistant_delegated_token_expires_at_monotonic",
                0.0,
            )
        )
        runtime_state.last_accessed_monotonic = self._time.monotonic()
        return new_session

    async def best_effort_rehydrate_swival_session(
        self,
        *,
        db: AsyncSession,
        current_user: Any,
        conversation_id: str,
        session: Any,
    ) -> None:
        persisted_messages = await self._persisted_messages_loader(
            db=db,
            current_user=current_user,
            conversation_id=conversation_id,
        )
        if not persisted_messages:
            return

        setup = getattr(session, "_setup", None)
        if callable(setup):
            try:
                await asyncio.to_thread(setup)
            except Exception:
                return

        existing_state = cast(
            dict[str, Any] | None, getattr(session, "_conv_state", None)
        )
        if isinstance(existing_state, dict):
            existing_messages = existing_state.get("messages")
            if isinstance(existing_messages, list) and any(
                not (isinstance(message, dict) and message.get("role") == "system")
                for message in existing_messages
            ):
                return

        make_state = getattr(session, "_make_per_run_state", None)
        if callable(make_state):
            system_content = None
            system_with_memory = getattr(session, "_system_with_memory", None)
            if callable(system_with_memory):
                try:
                    system_content = system_with_memory("", policy="interactive")
                except TypeError:
                    system_content = system_with_memory("")
            try:
                state = cast(
                    dict[str, Any],
                    make_state(system_content=cast(str | None, system_content)),
                )
            except TypeError:
                state = cast(dict[str, Any], make_state())
        else:
            state = {"messages": []}

        existing_messages = state.get("messages")
        system_messages = (
            [
                copy.deepcopy(message)
                for message in existing_messages
                if isinstance(message, dict) and message.get("role") == "system"
            ]
            if isinstance(existing_messages, list)
            else []
        )
        state["messages"] = system_messages + copy.deepcopy(persisted_messages)
        setattr(session, "_conv_state", state)

    def create_swival_session(
        self,
        *,
        current_user: Any,
        conversation_id: str,
        delegated_write_operation_ids: frozenset[str],
    ) -> Any:
        write_tools_enabled = bool(delegated_write_operation_ids)
        session_cls = self.load_swival_session_cls()
        tool_definitions = self.select_run_tool_definitions(
            allow_write_tools=write_tools_enabled,
            delegated_write_operation_ids=delegated_write_operation_ids,
        )
        delegated_token_ttl_seconds = self.delegated_token_ttl_seconds()
        token = create_hub_assistant_access_token(
            cast(Any, current_user.id),
            allowed_operations=[
                definition.operation_id for definition in tool_definitions
            ],
            delegated_by="hub_assistant",
            conversation_id=conversation_id,
        )
        session = session_cls(
            base_dir=self.resolve_swival_base_dir(current_user),
            provider=cast(str, settings.hub_assistant_swival_provider),
            model=cast(str, settings.hub_assistant_swival_model),
            api_key=settings.hub_assistant_swival_api_key,
            base_url=settings.hub_assistant_swival_base_url,
            max_turns=settings.hub_assistant_swival_max_turns,
            max_output_tokens=settings.hub_assistant_swival_max_output_tokens,
            reasoning_effort=settings.hub_assistant_swival_reasoning_effort,
            system_prompt=self.build_system_prompt(
                allow_write_tools=write_tools_enabled,
                delegated_write_operation_ids=delegated_write_operation_ids,
            ),
            files="none",
            commands="none",
            no_skills=True,
            history=False,
            memory=False,
            continue_here=False,
            yolo=False,
            mcp_servers={
                "a2a-client-hub": {
                    "url": self.build_mcp_url(allow_write_tools=write_tools_enabled),
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            },
        )
        setattr(
            session,
            "_hub_assistant_delegated_token_expires_at_monotonic",
            self._time.monotonic() + delegated_token_ttl_seconds,
        )
        return session

    def resolve_swival_base_dir(self, current_user: Any) -> str:
        configured_root = (settings.hub_assistant_swival_runtime_root or "").strip()
        if configured_root:
            runtime_root = Path(configured_root).expanduser()
        else:
            runtime_root = Path.home() / ".a2a-client-hub" / "swival-users"

        user_runtime_dir = runtime_root / str(current_user.id)
        user_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for candidate in (runtime_root, user_runtime_dir):
            try:
                candidate.chmod(0o700)
            except OSError:
                continue
        return str(user_runtime_dir.resolve())

    def build_session_conversation_state(self, session: Any) -> dict[str, Any] | None:
        conv_state = getattr(session, "_conv_state", None)
        if isinstance(conv_state, dict):
            return copy.deepcopy(conv_state)

        setup = getattr(session, "_setup", None)
        if callable(setup):
            try:
                setup()
            except Exception:
                return None
            conv_state = getattr(session, "_conv_state", None)
            if isinstance(conv_state, dict):
                return copy.deepcopy(conv_state)

        make_state = getattr(session, "_make_per_run_state", None)
        if not callable(make_state):
            return None

        system_content = None
        system_with_memory = getattr(session, "_system_with_memory", None)
        if callable(system_with_memory):
            try:
                system_content = system_with_memory("", policy="interactive")
            except TypeError:
                system_content = system_with_memory("")
            except Exception:
                system_content = None
        try:
            return cast(
                dict[str, Any],
                make_state(system_content=cast(str | None, system_content)),
            )
        except TypeError:
            return cast(dict[str, Any], make_state())
        except Exception:
            return None

    def transfer_conversation_state(
        self,
        previous_session: Any,
        next_session: Any,
    ) -> None:
        previous_state = self.build_session_conversation_state(previous_session)
        if previous_state is not None:
            next_state = self.build_session_conversation_state(next_session)
            previous_messages = previous_state.get("messages")
            next_messages = next_state.get("messages") if next_state else None
            previous_non_system_messages = (
                [
                    copy.deepcopy(message)
                    for message in previous_messages
                    if not (
                        isinstance(message, dict) and message.get("role") == "system"
                    )
                ]
                if isinstance(previous_messages, list)
                else []
            )
            next_system_messages = (
                [
                    copy.deepcopy(message)
                    for message in next_messages
                    if isinstance(message, dict) and message.get("role") == "system"
                ]
                if isinstance(next_messages, list)
                else []
            )
            transferred_state = copy.deepcopy(next_state) if next_state else {}
            transferred_state["messages"] = (
                next_system_messages + previous_non_system_messages
            )
            setattr(next_session, "_conv_state", transferred_state)
        trace_session_id = getattr(previous_session, "_trace_session_id", None)
        if isinstance(trace_session_id, str) and trace_session_id.strip():
            setattr(next_session, "_trace_session_id", trace_session_id)

    def close_swival_session(self, session: Any) -> None:
        close = getattr(session, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                return

    def load_swival_session_cls(self) -> type[Any]:
        self.inject_swival_import_paths()

        try:
            module = importlib.import_module("swival")
        except ImportError as exc:
            raise HubAssistantUnavailableError(
                "swival is not installed or not importable for the Hub Assistant runtime."
            ) from exc
        self.apply_swival_compatibility_patches()

        session_cls = getattr(module, "Session", None)
        if session_cls is None:
            raise HubAssistantUnavailableError(
                "swival.Session is required for the Hub Assistant runtime."
            )
        return cast(type[Any], session_cls)

    def apply_swival_compatibility_patches(self) -> None:
        try:
            module = __import__("swival.mcp_client", fromlist=["_mcp_tool_to_openai"])
        except ImportError:
            return

        converter = getattr(module, "_mcp_tool_to_openai", None)
        if not callable(converter) or getattr(
            converter,
            "_a2a_client_hub_private_field_patch",
            False,
        ):
            return

        def _patched_mcp_tool_to_openai(
            server_name: str, tool: Any
        ) -> tuple[dict, str]:
            schema, original_name = converter(server_name, tool)
            function_schema = schema.get("function")
            if isinstance(function_schema, dict):
                for key in list(function_schema.keys()):
                    if key.startswith("_mcp_"):
                        function_schema.pop(key, None)
            return schema, original_name

        setattr(
            _patched_mcp_tool_to_openai,
            "_a2a_client_hub_private_field_patch",
            True,
        )
        setattr(module, "_mcp_tool_to_openai", _patched_mcp_tool_to_openai)

    def has_required_runtime_configuration(self) -> bool:
        return bool(
            (settings.hub_assistant_swival_provider or "").strip()
            and (settings.hub_assistant_swival_model or "").strip()
            and (settings.hub_assistant_swival_mcp_base_url or "").strip()
        )

    def is_swival_importable(self) -> bool:
        loaded_module = sys.modules.get("swival")
        if (
            loaded_module is not None
            and getattr(loaded_module, "Session", None) is not None
        ):
            return True

        try:
            importlib.import_module("swival")
            return True
        except ImportError:
            pass

        for candidate in self.resolve_swival_import_paths():
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            try:
                importlib.import_module("swival")
                return True
            except ImportError:
                continue

        return False

    def inject_swival_import_paths(self) -> None:
        for candidate in self.resolve_swival_import_paths():
            if candidate not in sys.path:
                sys.path.insert(0, candidate)

    def resolve_swival_import_paths(self) -> list[str]:
        resolved_paths: list[str] = []
        seen: set[str] = set()
        for raw_path in settings.hub_assistant_swival_import_paths:
            candidate = raw_path.strip()
            if not candidate:
                continue
            resolved = str(Path(candidate).expanduser().resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            resolved_paths.append(resolved)

        for discovered in self.discover_swival_tool_import_paths():
            if discovered in seen:
                continue
            seen.add(discovered)
            resolved_paths.append(discovered)

        return resolved_paths

    def discover_swival_tool_import_paths(self) -> list[str]:
        executable_setting = (
            settings.hub_assistant_swival_tool_executable or ""
        ).strip()
        executable_path: str | None = None
        if executable_setting:
            candidate = Path(executable_setting).expanduser()
            if candidate.exists():
                executable_path = str(candidate.resolve())
            else:
                executable_path = shutil.which(executable_setting)
        else:
            executable_path = shutil.which("swival")

        if not executable_path:
            return []

        resolved_executable = Path(executable_path).expanduser().resolve()
        venv_bin_dir = resolved_executable.parent
        if venv_bin_dir.name not in {"bin", "Scripts"}:
            return []

        venv_root = venv_bin_dir.parent
        candidate_paths: list[str] = []
        for site_packages in sorted(venv_root.glob("lib/python*/site-packages")):
            candidate_paths.append(str(site_packages.resolve()))

        windows_site_packages = venv_root / "Lib" / "site-packages"
        if windows_site_packages.exists():
            candidate_paths.append(str(windows_site_packages.resolve()))

        return candidate_paths
