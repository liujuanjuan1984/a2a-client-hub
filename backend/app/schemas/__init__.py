"""
Pydantic schemas

This package contains all Pydantic model definitions for data validation.
"""

from app.schemas.actual_event import (
    ActualEventCreate,
    ActualEventResponse,
    ActualEventTaskSummary,
    ActualEventUpdate,
    ActualEventWithEnergyResponse,
)
from app.schemas.actual_event_quick_template import (
    ActualEventQuickTemplateBulkCreateRequest,
    ActualEventQuickTemplateCreate,
    ActualEventQuickTemplateListResponse,
    ActualEventQuickTemplateReorderRequest,
    ActualEventQuickTemplateResponse,
    ActualEventQuickTemplateUpdate,
)
from app.schemas.dimension import DimensionListResponse, DimensionSummaryResponse
from app.schemas.entity_ingest import (
    EntityExtraction,
    EntityIngestRequest,
    EntityIngestResponse,
    HabitDraft,
    NoteDraft,
    PersonDraft,
    TagDraft,
    TaskDraft,
    VisionDraft,
)
from app.schemas.finance_exchange_rates import (
    ExchangeRateCreateRequest,
    ExchangeRateQueryResponse,
    ExchangeRateQueryResult,
    ExchangeRateResponse,
)
from app.schemas.food import (
    FoodCreate,
    FoodListResponse,
    FoodResponse,
    FoodSummary,
    FoodUpdate,
)
from app.schemas.food_entry import (
    DailyNutritionSummary,
    FoodEntryCreate,
    FoodEntryListResponse,
    FoodEntryResponse,
    FoodEntrySummary,
    FoodEntryUpdate,
)
from app.schemas.habit import (
    HabitActionCreate,
    HabitActionListResponse,
    HabitActionResponse,
    HabitActionUpdate,
    HabitActionWithHabit,
    HabitBase,
    HabitCreate,
    HabitListResponse,
    HabitResponse,
    HabitStatsResponse,
    HabitUpdate,
    HabitWithActions,
)
from app.schemas.note import NoteCreate, NoteIngestJobSummary, NoteResponse, NoteUpdate
from app.schemas.person import (
    AnniversaryCreate,
    AnniversaryResponse,
    PersonActivitiesResponse,
    PersonActivityItem,
    PersonCreate,
    PersonDetailListResponse,
    PersonListResponse,
    PersonResponse,
    PersonSummaryResponse,
    PersonUpdate,
)
from app.schemas.planned_event import (
    PlannedEventCreate,
    PlannedEventListResponse,
    PlannedEventRangeListResponse,
    PlannedEventResponse,
    PlannedEventUpdate,
)
from app.schemas.task import (
    TaskCreate,
    TaskHierarchy,
    TaskMoveRequest,
    TaskMoveResponse,
    TaskReorderRequest,
    TaskResponse,
    TaskStatsResponse,
    TaskStatusUpdate,
    TaskUpdate,
    TaskWithSubtasks,
)
from app.schemas.vision import (
    VisionCreate,
    VisionExperienceUpdate,
    VisionHarvestRequest,
    VisionListResponse,
    VisionResponse,
    VisionStatsResponse,
    VisionSummaryResponse,
    VisionUpdate,
    VisionWithTasks,
)

__all__ = [
    "PlannedEventCreate",
    "PlannedEventListResponse",
    "PlannedEventRangeListResponse",
    "PlannedEventResponse",
    "PlannedEventUpdate",
    "ActualEventCreate",
    "ActualEventResponse",
    "ActualEventTaskSummary",
    "ActualEventUpdate",
    "ActualEventWithEnergyResponse",
    "FoodCreate",
    "FoodListResponse",
    "FoodResponse",
    "FoodSummary",
    "FoodUpdate",
    "FoodEntryCreate",
    "FoodEntryListResponse",
    "FoodEntryResponse",
    "FoodEntrySummary",
    "FoodEntryUpdate",
    "DailyNutritionSummary",
    "HabitActionCreate",
    "HabitActionListResponse",
    "HabitActionResponse",
    "HabitActionUpdate",
    "HabitActionWithHabit",
    "HabitBase",
    "HabitCreate",
    "HabitListResponse",
    "HabitResponse",
    "HabitStatsResponse",
    "HabitUpdate",
    "HabitWithActions",
    "EntityIngestRequest",
    "EntityIngestResponse",
    "EntityExtraction",
    "TagDraft",
    "PersonDraft",
    "VisionDraft",
    "TaskDraft",
    "HabitDraft",
    "NoteDraft",
    "NoteCreate",
    "NoteIngestJobSummary",
    "NoteResponse",
    "NoteUpdate",
    "PersonCreate",
    "PersonDetailListResponse",
    "PersonResponse",
    "PersonUpdate",
    "PersonListResponse",
    "PersonSummaryResponse",
    "PersonActivitiesResponse",
    "PersonActivityItem",
    "AnniversaryCreate",
    "AnniversaryResponse",
    "TaskCreate",
    "TaskResponse",
    "TaskUpdate",
    "TaskStatusUpdate",
    "TaskWithSubtasks",
    "TaskHierarchy",
    "TaskMoveRequest",
    "TaskMoveResponse",
    "TaskReorderRequest",
    "TaskStatsResponse",
    "DimensionListResponse",
    "DimensionSummaryResponse",
    "VisionCreate",
    "VisionListResponse",
    "VisionResponse",
    "VisionUpdate",
    "VisionExperienceUpdate",
    "VisionHarvestRequest",
    "VisionWithTasks",
    "VisionStatsResponse",
    "VisionSummaryResponse",
    "ActualEventQuickTemplateCreate",
    "ActualEventQuickTemplateUpdate",
    "ActualEventQuickTemplateResponse",
    "ActualEventQuickTemplateListResponse",
    "ActualEventQuickTemplateReorderRequest",
    "ActualEventQuickTemplateBulkCreateRequest",
    "ExchangeRateCreateRequest",
    "ExchangeRateResponse",
    "ExchangeRateQueryResponse",
    "ExchangeRateQueryResult",
]

# Rebuild models to resolve forward references after all imports are complete
# Order matters: rebuild base models first, then dependent models
NoteResponse.model_rebuild()
PlannedEventResponse.model_rebuild()
ActualEventResponse.model_rebuild()
TaskResponse.model_rebuild()
TaskMoveResponse.model_rebuild()
TaskWithSubtasks.model_rebuild()
VisionResponse.model_rebuild()
VisionWithTasks.model_rebuild()
ActualEventWithEnergyResponse.model_rebuild()
