"""
Effort aggregation services for tasks.

This module maintains `actual_effort_self` and `actual_effort_total` for tasks
based on `ActualEvent` time entries. It provides idempotent recomputation
utilities designed to be called within the same DB transaction as the mutations
that affect time entries or task hierarchy.
"""

from __future__ import annotations

from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.actual_event import ActualEvent
from app.db.models.task import Task


def _event_minutes(event: ActualEvent) -> int:
    """Return whole minutes for a finished event; zero if ongoing or invalid."""
    # end_time and start_time are now always required, no need to check for None
    delta = event.end_time - event.start_time
    if delta.total_seconds() <= 0:  # type: ignore[attr-defined]
        return 0
    return int(delta.total_seconds() // 60)  # type: ignore[attr-defined]


def recompute_task_self_minutes(db: Session, task_id: UUID) -> int:
    """
    Recompute and persist `actual_effort_self` for a single task by summing minutes
    of all non-deleted, finished `ActualEvent`s that reference this task via task_id.

    Returns the computed minutes.
    """
    task: Optional[Task] = Task.active(db).filter(Task.id == task_id).first()
    if task is None:
        return 0

    # Load finished events for this task
    events: List[ActualEvent] = (
        ActualEvent.active(db)
        .filter(
            ActualEvent.task_id == task_id,
            # end_time is now always required, no need to filter for non-null
        )
        .all()
    )

    total_minutes = sum(_event_minutes(e) for e in events)
    task.actual_effort_self = total_minutes
    # Do not commit here; caller should manage transaction
    return total_minutes


def recompute_totals_upwards(db: Session, start_task_id: UUID) -> None:
    """
    Recompute `actual_effort_total` for the start task and all its ancestors.

    For each visited node: total = self + sum(child.total)
    """
    # Build ancestor chain
    chain: List[Task] = []
    current = Task.active(db).filter(Task.id == start_task_id).first()
    while current is not None:
        chain.append(current)
        if current.parent_task_id is None:
            break
        current = Task.active(db).filter(Task.id == current.parent_task_id).first()

    # Recompute from bottom to top so children totals are ready
    # First ensure each node has up-to-date self minutes (caller may have done this already)
    visited_ids: Set[int] = set()
    for node in chain:
        if node.id in visited_ids:
            continue
        visited_ids.add(node.id)
        if node.actual_effort_self is None:
            recompute_task_self_minutes(db, node.id)

    for node in chain:
        # Sum children totals
        children = Task.active(db).filter(Task.parent_task_id == node.id).all()
        child_total = sum(c.actual_effort_total or 0 for c in children)
        node.actual_effort_total = (node.actual_effort_self or 0) + child_total


def recompute_subtree_totals(db: Session, subtree_root_id: UUID) -> None:
    """
    Recompute totals for an entire subtree rooted at `subtree_root_id` using a
    post-order traversal.
    """
    # Load all tasks in this vision subtree by BFS and then compute post-order
    root = Task.active(db).filter(Task.id == subtree_root_id).first()
    if root is None:
        return

    # Gather nodes
    stack = [root]
    nodes: List[Task] = []
    while stack:
        node = stack.pop()
        nodes.append(node)
        children = Task.active(db).filter(Task.parent_task_id == node.id).all()
        stack.extend(children)

    # Ensure self minutes
    for node in nodes:
        recompute_task_self_minutes(db, node.id)

    # Post-order: compute totals such that children are processed first
    processed: Set[int] = set()

    def _compute(node: Task) -> int:
        if node.id in processed:
            return node.actual_effort_total or 0
        children = Task.active(db).filter(Task.parent_task_id == node.id).all()
        total_children = sum(_compute(c) for c in children)
        node.actual_effort_total = (node.actual_effort_self or 0) + total_children
        processed.add(node.id)
        return node.actual_effort_total

    _compute(root)
