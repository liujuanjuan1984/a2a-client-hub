"""Aggregate imports to register all tool guides."""

# Importing submodules executes their register_tool calls.
from . import (  # noqa: F401
    food,
    habits,
    integrations,
    notes,
    persons,
    preferences,
    tags,
    tasks,
    timelog,
    visions,
)

__all__ = []
