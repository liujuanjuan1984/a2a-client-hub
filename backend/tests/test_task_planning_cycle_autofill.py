from app.agents.tools.task_tools import resolve_planning_cycle_days


def test_resolve_planning_cycle_days_autofills_week():
    assert resolve_planning_cycle_days("week", None) == 7


def test_resolve_planning_cycle_days_preserves_existing_value():
    assert resolve_planning_cycle_days("day", 3) == 3


def test_resolve_planning_cycle_days_handles_unknown_type():
    assert resolve_planning_cycle_days("custom", None) is None
