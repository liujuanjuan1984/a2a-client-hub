"""Shared types for the Hub Assistant runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from app.features.hub_assistant.shared.constants import HUB_ASSISTANT_PUBLIC_ID
from app.features.hub_assistant.shared.hub_assistant_tool_contract import (
    HubAssistantToolDefinition,
)

DEFAULT_AGENT_ID = HUB_ASSISTANT_PUBLIC_ID
DEFAULT_AGENT_NAME = "A2A Client Hub Assistant"
DEFAULT_AGENT_DESCRIPTION = (
    "A swival-backed Hub Assistant that can manage the authenticated user's own "
    "a2a-client-hub resources through constrained Hub Assistant tools."
)
FOLLOW_UP_RESUME_MESSAGE_TEMPLATE = (
    "System follow-up wakeup: newer persisted target-session text results were "
    "detected for this Hub Assistant conversation.\n\n"
    "Tracked target conversation ids: {tracked_conversation_ids}\n"
    "Changed target conversation ids: {changed_conversation_ids}\n"
    "Previously acknowledged target-agent anchors by conversation: "
    "{previous_target_agent_message_anchors}\n"
    "Previously acknowledged target-agent text message ids by conversation: "
    "{previous_target_agent_message_ids}\n"
    "Currently observed latest target-agent anchors by conversation: "
    "{observed_target_agent_message_anchors}\n\n"
    "Use `hub_assistant.followups.get` to inspect the durable follow-up state, then use "
    "`hub_assistant.sessions.get_latest_messages` with "
    "`after_agent_message_id_by_conversation` set to the previous message-id "
    "map above so you only read newly persisted target-agent text results. "
    "Summarize meaningful progress or conclusions to the user. If you need to "
    "adjust future tracking scope, call `hub_assistant.followups.set_sessions` with the "
    "exact target conversation ids that should remain tracked. Pass an empty "
    "list when tracking should stop. Do not wait on downstream live transport."
)


class HubAssistantError(RuntimeError):
    """Base error for the Hub Assistant runtime."""


class HubAssistantConfigError(HubAssistantError):
    """Raised when the Hub Assistant runtime is not configured."""


class HubAssistantUnavailableError(HubAssistantError):
    """Raised when the swival runtime cannot be imported or executed."""


class HubAssistantRunStatus(str, Enum):
    """High-level outcome for one Hub Assistant run."""

    ACCEPTED = "accepted"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class HubAssistantInterrupt:
    """Permission interrupt emitted by a read-only Hub Assistant run."""

    request_id: str
    permission: str
    patterns: tuple[str, ...]
    display_message: str


@dataclass(frozen=True)
class HubAssistantProfile:
    """Static metadata for the swival-backed Hub Assistant."""

    agent_id: str
    name: str
    description: str
    runtime: str
    configured: bool
    resources: tuple[str, ...]
    tool_definitions: tuple[HubAssistantToolDefinition, ...]


@dataclass(frozen=True)
class HubAssistantContinuation:
    """Accepted continuation details returned immediately to the caller."""

    phase: str
    agent_message_id: UUID


@dataclass(frozen=True)
class HubAssistantRunResult:
    """One completed or interrupted swival-backed Hub Assistant run."""

    status: HubAssistantRunStatus
    answer: str | None
    exhausted: bool
    runtime: str
    resources: tuple[str, ...]
    tool_names: tuple[str, ...]
    write_tools_enabled: bool
    interrupt: HubAssistantInterrupt | None = None
    continuation: HubAssistantContinuation | None = None


@dataclass(frozen=True)
class HubAssistantRecoveredInterrupt:
    """One unresolved persisted interrupt recovered from durable session history."""

    request_id: str
    session_id: str
    type: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ExecutedHubAssistantRun:
    """Internal swival execution result together with durable session context."""

    result: HubAssistantRunResult
    profile: HubAssistantProfile
    local_session: Any
    local_session_id: str
    local_source: str


@dataclass
class ConversationRuntimeState:
    """One in-memory swival conversation runtime owned by one user conversation."""

    session: Any | None = None
    delegated_write_operation_ids: frozenset[str] = frozenset()
    auto_approve_write_operation_ids: frozenset[str] = frozenset()
    delegated_token_expires_at_monotonic: float = 0.0
    last_accessed_monotonic: float = 0.0
    lock: asyncio.Lock | None = None

    def get_lock(self) -> asyncio.Lock:
        if self.lock is None:
            self.lock = asyncio.Lock()
        return self.lock
