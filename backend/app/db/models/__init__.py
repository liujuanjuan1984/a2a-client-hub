"""
SQLAlchemy models

This package contains all SQLAlchemy model definitions.
"""

from app.db.models.a2a_agent import A2AAgent
from app.db.models.a2a_agent_credential import A2AAgentCredential
from app.db.models.a2a_schedule_execution import A2AScheduleExecution
from app.db.models.a2a_schedule_task import A2AScheduleTask
from app.db.models.actual_event import ActualEvent
from app.db.models.actual_event_quick_template import ActualEventQuickTemplate
from app.db.models.agent_audit_log import AgentAuditLog
from app.db.models.agent_message import AgentMessage
from app.db.models.agent_message_receipt import AgentMessageReceipt
from app.db.models.agent_session import AgentSession
from app.db.models.aggregated_dimension_stat import AggregatedDimensionStat
from app.db.models.anniversary import Anniversary
from app.db.models.association import Association
from app.db.models.daily_dimension_stat import DailyDimensionStat
from app.db.models.daily_review_run import DailyReviewRun
from app.db.models.dimension import Dimension
from app.db.models.finance_accounts import FinanceAccount, FinanceAccountTree
from app.db.models.finance_balance_snapshots import (
    FinanceSnapshot,
    FinanceSnapshotEntry,
)
from app.db.models.finance_cashflow import (
    CashflowBillingEntry,
    CashflowSnapshot,
    CashflowSnapshotEntry,
    CashflowSource,
    CashflowSourceTree,
)
from app.db.models.finance_trading import (
    ExchangeRate,
    TradingEntry,
    TradingInstrument,
    TradingInstrumentMetric,
    TradingPlan,
)
from app.db.models.food import Food
from app.db.models.food_entry import FoodEntry
from app.db.models.habit import Habit
from app.db.models.habit_action import HabitAction
from app.db.models.invitation import Invitation, InvitationStatus
from app.db.models.note import Note
from app.db.models.note_ingest_job import NoteIngestJob
from app.db.models.person import Person
from app.db.models.planned_event import PlannedEvent
from app.db.models.planned_event_occurrence_exception import (
    PlannedEventOccurrenceException,
)
from app.db.models.sage_maxim import SageMaxim, SageMaximReaction
from app.db.models.tag import Tag
from app.db.models.tag_associations import tag_associations
from app.db.models.task import Task
from app.db.models.user import User
from app.db.models.user_activity import UserActivity
from app.db.models.user_daily_llm_usage import UserDailyLlmUsage
from app.db.models.user_llm_credential import UserLlmCredential
from app.db.models.user_preference import UserPreference
from app.db.models.vision import Vision
from app.db.models.work_recalc_job import WorkRecalcJob
from app.db.models.ws_ticket import WsTicket

__all__ = [
    "tag_associations",
    "ActualEvent",
    "A2AAgent",
    "A2AAgentCredential",
    "A2AScheduleExecution",
    "A2AScheduleTask",
    "AgentAuditLog",
    "AgentMessage",
    "AgentMessageReceipt",
    "AgentSession",
    "Anniversary",
    "Association",
    "AggregatedDimensionStat",
    "DailyDimensionStat",
    "DailyReviewRun",
    "Dimension",
    "FinanceAccount",
    "FinanceAccountTree",
    "FinanceSnapshot",
    "FinanceSnapshotEntry",
    "CashflowSource",
    "CashflowSourceTree",
    "CashflowSnapshot",
    "CashflowSnapshotEntry",
    "CashflowBillingEntry",
    "TradingPlan",
    "TradingInstrument",
    "TradingEntry",
    "TradingInstrumentMetric",
    "ExchangeRate",
    "Food",
    "FoodEntry",
    "Habit",
    "HabitAction",
    "Invitation",
    "InvitationStatus",
    "Note",
    "NoteIngestJob",
    "Person",
    "PlannedEvent",
    "PlannedEventOccurrenceException",
    "SageMaxim",
    "SageMaximReaction",
    "Tag",
    "Task",
    "ActualEventQuickTemplate",
    "User",
    "UserActivity",
    "UserDailyLlmUsage",
    "UserLlmCredential",
    "UserPreference",
    "Vision",
    "WorkRecalcJob",
    "WsTicket",
]
