"""SQLAlchemy models registry.

This package intentionally exposes the minimal set of models required for the
A2A client backend cut. Alembic imports this package to populate metadata for
autogeneration.
"""

from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.a2a_proxy_allowlist import A2AProxyAllowlist
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_block import AgentMessageBlock
from app.db.models.auth_audit_event import AuthAuditEvent
from app.db.models.auth_legacy_refresh_revocation import AuthLegacyRefreshRevocation
from app.db.models.auth_refresh_session import AuthRefreshSession
from app.db.models.conversation_thread import ConversationThread
from app.db.models.external_session_directory_cache import (
    ExternalSessionDirectoryCacheEntry,
)
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from app.db.models.hub_a2a_user_credential import HubA2AUserCredential
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.shortcut import Shortcut
from app.db.models.user import User
from app.db.models.ws_ticket import WsTicket

__all__ = [
    "A2AAgent",
    "A2AAgentCredential",
    "A2AProxyAllowlist",
    "A2AScheduleExecution",
    "A2AScheduleTask",
    "AgentMessageBlock",
    "AgentMessage",
    "AuthAuditEvent",
    "AuthLegacyRefreshRevocation",
    "AuthRefreshSession",
    "ConversationThread",
    "HubA2AAgentAllowlistEntry",
    "HubA2AUserCredential",
    "Invitation",
    "InvitationStatus",
    "ExternalSessionDirectoryCacheEntry",
    "User",
    "Shortcut",
    "WsTicket",
]
