"""
Async counterparts for task effort aggregation helpers.

这些函数与 ``app.handlers.metrics.effort`` 保持逻辑一致，但直接使用
``AsyncSession``，避免在 async handler 中频繁调用 ``run_sync``。
"""

from __future__ import annotations

from collections import deque
from typing import List, Optional, Sequence, Set
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.actual_event import ActualEvent
from app.db.models.task import Task
from app.handlers.metrics.effort import _event_minutes


async def _load_active_task(db: AsyncSession, task_id: UUID) -> Optional[Task]:
    stmt: Select[Task] = (
        select(Task).where(Task.id == task_id, Task.deleted_at.is_(None)).limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_children(db: AsyncSession, parent_id: UUID) -> List[Task]:
    stmt: Select[Task] = select(Task).where(
        Task.parent_task_id == parent_id,
        Task.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def recompute_task_self_minutes(db: AsyncSession, task_id: UUID) -> int:
    task = await _load_active_task(db, task_id)
    if task is None:
        return 0

    stmt: Select[ActualEvent] = select(ActualEvent).where(
        ActualEvent.task_id == task_id,
        ActualEvent.deleted_at.is_(None),
    )
    events = (await db.execute(stmt)).scalars().all()
    total_minutes = sum(_event_minutes(event) for event in events)
    task.actual_effort_self = total_minutes
    return total_minutes


async def recompute_totals_upwards(db: AsyncSession, start_task_id: UUID) -> None:
    chain: List[Task] = []
    current = await _load_active_task(db, start_task_id)
    while current is not None:
        chain.append(current)
        if current.parent_task_id is None:
            break
        current = await _load_active_task(db, current.parent_task_id)

    visited: Set[UUID] = set()
    for node in chain:
        if node.id in visited:
            continue
        visited.add(node.id)
        if node.actual_effort_self is None:
            await recompute_task_self_minutes(db, node.id)

    for node in chain:
        children = await _load_children(db, node.id)
        child_total = sum(child.actual_effort_total or 0 for child in children)
        node.actual_effort_total = (node.actual_effort_self or 0) + child_total


async def recompute_subtree_totals(db: AsyncSession, subtree_root_id: UUID) -> None:
    root = await _load_active_task(db, subtree_root_id)
    if root is None:
        return

    queue: deque[Task] = deque([root])
    nodes: List[Task] = []
    while queue:
        node = queue.popleft()
        nodes.append(node)
        children = await _load_children(db, node.id)
        queue.extend(children)

    for node in nodes:
        await recompute_task_self_minutes(db, node.id)

    processed: Set[UUID] = set()

    async def _compute(node: Task) -> int:
        if node.id in processed:
            return node.actual_effort_total or 0
        children = await _load_children(db, node.id)
        total_children = 0
        for child in children:
            total_children += await _compute(child)
        node.actual_effort_total = (node.actual_effort_self or 0) + total_children
        processed.add(node.id)
        return node.actual_effort_total

    await _compute(root)


__all__: Sequence[str] = [
    "recompute_subtree_totals",
    "recompute_task_self_minutes",
    "recompute_totals_upwards",
]
