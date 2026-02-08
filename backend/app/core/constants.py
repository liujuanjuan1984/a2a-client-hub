"""
Core constants for the application
"""

# Task hierarchy limits
MAX_TASK_DEPTH = 5  # Maximum allowed depth for task hierarchy

# Allowed status sets (centralized to avoid duplication)
TASK_ALLOWED_STATUSES = {"todo", "in_progress", "done", "cancelled", "paused"}
VISION_ALLOWED_STATUSES = {"active", "archived", "fruit"}
VISION_EXPERIENCE_RATE_DEFAULT = 60
VISION_EXPERIENCE_RATE_MAX = 3600
PLANNED_EVENT_ALLOWED_STATUSES = {"planned", "cancelled", "done"}
PLANNED_EVENT_EXCEPTION_ACTION_SKIP = "skip"
PLANNED_EVENT_EXCEPTION_ACTION_TRUNCATE = "truncate"
PLANNED_EVENT_EXCEPTION_ACTION_OVERRIDE = "override"

# Habit constants
HABIT_ALLOWED_STATUSES = {"active", "completed", "paused", "expired"}

# Habit action status configuration - Single source of truth for backend
HABIT_ACTION_STATUS_CONFIG = {
    "pending": {
        "display_name": "待办",
        "color": "blue",
        "default_for_new": True,
        "manual_status": False,
        "count_as_completed": False,
    },
    "done": {
        "display_name": "已完成",
        "color": "green",
        "default_for_new": False,
        "manual_status": True,
        "count_as_completed": True,
    },
    "skip": {
        "display_name": "跳过",
        "color": "gray",
        "default_for_new": False,
        "manual_status": True,
        "count_as_completed": False,
    },
    "miss": {
        "display_name": "错过",
        "color": "red",
        "default_for_new": False,
        "manual_status": True,
        "count_as_completed": False,
    },
}


def get_habit_action_allowed_statuses() -> set[str]:
    return set(HABIT_ACTION_STATUS_CONFIG.keys())


def get_default_habit_action_status() -> str:
    for status, cfg in HABIT_ACTION_STATUS_CONFIG.items():
        if cfg.get("default_for_new"):
            return status
    raise ValueError(
        "No default habit action status configured in HABIT_ACTION_STATUS_CONFIG"
    )


HABIT_DURATION_OPTIONS = {7, 14, 21, 100, 365, 1000}
HABIT_EDITABLE_DAYS = 10000  # How many days after action date editing is allowed
MAX_ACTIVE_HABITS = 99  # Maximum number of simultaneously active habits per user
DEFAULT_HABIT_ACTION_WINDOW_DAYS = 5  # Default days captured around a reference date
MAX_HABIT_ACTION_WINDOW_DAYS = (
    100  # Maximum number of days returned for date window queries
)

# Planning cycle constants
PLANNING_CYCLE_TYPES = {"year", "month", "week", "day"}

# Appearance/theme options shared with frontend theme selector
APP_THEME_OPTIONS = {
    "system",
    "fresh",
    "cupcake",
    "bumblebee",
    "emerald",
    "corporate",
    "synthwave",
    "retro",
    "cyberpunk",
    "valentine",
    "halloween",
    "garden",
    "forest",
    "aqua",
    "lofi",
    "pastel",
    "fantasy",
    "wireframe",
    "luxury",
    "dracula",
    "cmyk",
    "autumn",
    "business",
    "acid",
    "lemonade",
    "night",
    "coffee",
    "winter",
}

# Navigation defaults and allowed modules for preference validation.
NAVIGATION_VISIBLE_MODULE_DEFAULTS = [
    "agent",
    "visions",
    "tree",
    "planning",
    "habits",
    "timelog",
    "insights",
    "calendar",
    "notes",
    "persons",
]

NAVIGATION_VISIBLE_MODULE_OPTIONS = {
    "agent",
    "tree",
    "visions",
    "calendar",
    "timelog",
    "planning",
    "notes",
    "persons",
    "insights",
    "habits",
    "food-diary",
    "finance",
    "sage-maxims",
    "invitations",
}


# Planning cycle days by calendar system
PLANNING_CYCLE_DAYS_BY_CALENDAR = {
    "gregorian": {
        "year": 365,
        "month": 30,  # Default month length for Gregorian
        "week": 7,
        "day": 1,
    },
    "mayan_13_moon": {
        "year": 365,
        "month": 28,  # Mayan months are always 28 days
        "week": 7,
        "day": 1,
    },
}

# Calendar system options
CALENDAR_SYSTEM_OPTIONS = {"gregorian", "mayan_13_moon"}

# User preference default values
# This configuration defines default values for user preferences
# When a user requests a preference that doesn't exist, the system will
# automatically create it with the corresponding default value
USER_PREFERENCE_DEFAULTS = {
    "appearance.theme": {
        "value": "system",
        "module": "appearance",
        "description": "Application appearance theme",
        "allowed_values": APP_THEME_OPTIONS,
    },
    "calendar.first_day_of_week": {
        "value": 1,  # ISO-8601 Monday
        "module": "calendar",
        "description": "First day of the week (1=Monday, 7=Sunday)",
        "allowed_values": {1, 2, 3, 4, 5, 6, 7},
    },
    "calendar.system": {
        "value": "gregorian",  # Default calendar system
        "module": "calendar",
        "description": "Calendar system (gregorian, mayan_13_moon)",
        "allowed_values": CALENDAR_SYSTEM_OPTIONS,
    },
    # Visible modules in the top navigation rail
    # Stored as a list of module keys. Allowed values are validated in API.
    "navigation.visible_modules": {
        "value": NAVIGATION_VISIBLE_MODULE_DEFAULTS,
        "module": "navigation",
        "description": "Visible modules in top navigation (list of module keys)",
        # Allowed values set. Validation for list types is handled in router.
        "allowed_values": NAVIGATION_VISIBLE_MODULE_OPTIONS,
    },
    "visions.experience_rate_per_hour": {
        "value": VISION_EXPERIENCE_RATE_DEFAULT,
        "module": "visions",
        "description": "Experience points gained per hour of actual effort for visions",
        "allowed_values": None,
        "validator": "vision_experience_rate_validator",
    },
    # Default planning preset when creating new tasks
    "tasks.default_planning_preset": {
        "value": "none",
        "module": "tasks",
        "description": "Default planning preset for new tasks (none, today, this_week, this_month)",
        "allowed_values": {"none", "today", "this_week", "this_month"},
    },
    # Dashboard dimension display order
    "dashboard.dimension_order": {
        "value": [],
        "module": "dimensions",
        "description": "Custom order for dimensions in dashboard stats view (list of dimension IDs)",
        "allowed_values": None,  # Will be validated against existing dimension IDs
        "validator": "dimension_validator",  # Use dimension validator
    },
    # Default inbox vision for todos
    "todos.default_inbox_vision": {
        "value": None,  # Will be set to user's first vision ID
        "module": "todos",
        "description": "Default vision for inbox todos (vision ID)",
        "allowed_values": None,  # Will be validated against user's active visions
        "validator": "vision_validator",  # Use vision validator
    },
    # Auto set task planning when creating time logs with related tasks
    "timeLog.auto_set_task_planning": {
        "value": False,
        "module": "timeLog",
        "description": "Automatically set task planning to today when creating time logs with related tasks",
        "allowed_values": {True, False},
    },
    # Show habit actions in daily planning view
    "planning.show_habit_actions": {
        "value": False,
        "module": "planning",
        "description": "Show active habit actions in daily planning view",
        "allowed_values": {True, False},
    },
    # Interface language preference
    "system.language": {
        "value": "auto",  # auto, zh, en
        "module": "system",
        "description": "Application interface language (auto, zh, en)",
        "allowed_values": {"auto", "zh", "en"},
    },
    "system.timezone": {
        "value": "UTC",
        "module": "system",
        "description": "Preferred timezone in IANA format (e.g. 'America/Los_Angeles')",
        "allowed_values": None,
        "validator": "timezone_validator",
    },
    # Floating agent visibility state
    "agent.floating_agent_visible": {
        "value": False,
        "module": "agent",
        "description": "Floating agent visibility state",
        "allowed_values": {True, False},
    },
    "notes.card_min_collapsed_lines": {
        "value": 5,
        "module": "notes",
        "description": "Minimum number of lines visible before expanding note content",
        "allowed_values": {3, 5, 7, 9, 15, 25, 50},
    },
    "notes.export_planning.include_task_notes": {
        "value": True,
        "module": "notes",
        "description": "Include task-related notes when exporting planning",
        "allowed_values": {True, False},
    },
    "notes.export_planning.include_cycle_notes": {
        "value": False,
        "module": "notes",
        "description": "Include cycle-date-range notes when exporting planning",
        "allowed_values": {True, False},
    },
    "finance.favorite_tags": {
        "value": [],
        "module": "finance",
        "description": "Pinned finance tags used to surface related notes",
        "allowed_values": None,
    },
    "finance.primary_currency": {
        "value": "USD",
        "module": "finance",
        "description": "Primary currency for finance tracking (supports both fiat and cryptocurrency codes)",
        "allowed_values": None,  # Uses currency_validator for format validation
        "validator": "currency_validator",
    },
}
