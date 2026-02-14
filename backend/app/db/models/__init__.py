"""SQLAlchemy models registry.

This package intentionally exposes the minimal set of models required for the
A2A client backend cut. Alembic imports this package to populate metadata for
autogeneration.
"""

from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_session import AgentSession
from app.db.models.conversation_binding import ConversationBinding
from app.db.models.conversation_thread import ConversationThread
from app.db.models.hub_a2a_agent import HubA2AAgent
from app.db.models.hub_a2a_agent_allowlist import HubA2AAgentAllowlistEntry
from app.db.models.hub_a2a_agent_credential import HubA2AAgentCredential
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.opencode_session_cache import OpencodeSessionCacheEntry
from app.db.models.user import User
from app.db.models.ws_ticket import WsTicket

__all__ = [
    "A2AAgent",
    "A2AAgentCredential",
    "A2AScheduleExecution",
    "A2AScheduleTask",
    "AgentMessage",
    "AgentSession",
    "ConversationBinding",
    "ConversationThread",
    "HubA2AAgent",
    "HubA2AAgentCredential",
    "HubA2AAgentAllowlistEntry",
    "Invitation",
    "InvitationStatus",
    "OpencodeSessionCacheEntry",
    "User",
    "WsTicket",
]
