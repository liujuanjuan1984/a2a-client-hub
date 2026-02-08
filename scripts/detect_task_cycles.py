"""Detect cyclic parent-child relationships in the tasks table.

Usage examples
--------------

.. code-block:: bash

    # 扫描所有任务（仅活跃记录）
    python -m scripts.detect_task_cycles

    # 限定某个用户
    python -m scripts.detect_task_cycles --user-id 123e4567-e89b-12d3-a456-426614174000

    # 限定某个愿景
    python -m scripts.detect_task_cycles --vision-id 123e4567-e89b-12d3-a456-426614174000
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set
from uuid import UUID

# Ensure the project root is importable when executed as a module/script.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.models.task import Task
from app.db.session import SessionLocal


@dataclass(frozen=True)
class TaskNode:
    """Lightweight task projection used for cycle detection."""

    id: UUID
    parent_id: Optional[UUID]
    vision_id: Optional[UUID]
    user_id: Optional[UUID]
    content: str


def _load_tasks(
    *,
    user_id: Optional[UUID],
    vision_id: Optional[UUID],
    include_deleted: bool,
) -> List[TaskNode]:
    session = SessionLocal()
    try:
        query = session.query(Task)

        if not include_deleted:
            query = query.filter(Task.deleted_at.is_(None))

        if user_id is not None:
            query = query.filter(Task.user_id == user_id)

        if vision_id is not None:
            query = query.filter(Task.vision_id == vision_id)

        tasks: List[TaskNode] = []
        for task in query.all():
            tasks.append(
                TaskNode(
                    id=task.id,
                    parent_id=task.parent_task_id,
                    vision_id=getattr(task, "vision_id", None),
                    user_id=getattr(task, "user_id", None),
                    content=(task.content or "")[:120],
                )
            )
        return tasks
    finally:
        session.close()


def _find_cycles(tasks: Iterable[TaskNode]) -> List[List[TaskNode]]:
    by_id: Dict[UUID, TaskNode] = {task.id: task for task in tasks}
    parent_map: Dict[UUID, Optional[UUID]] = {
        task.id: task.parent_id for task in tasks
    }
    visited_global: Set[UUID] = set()
    cycles: List[List[TaskNode]] = []

    for root_id in parent_map.keys():
        if root_id in visited_global:
            continue

        path: List[UUID] = []
        index_map: Dict[UUID, int] = {}
        current = root_id

        while current:
            if current in visited_global:
                break

            if current in index_map:
                start_idx = index_map[current]
                cycle_ids = path[start_idx:]
                cycles.append([by_id[node_id] for node_id in cycle_ids])
                break

            index_map[current] = len(path)
            path.append(current)

            parent = parent_map.get(current)
            if parent is None:
                break
            current = parent

        visited_global.update(path)

    return cycles


def _group_cycles_by_vision(cycles: Iterable[List[TaskNode]]) -> Dict[Optional[UUID], List[List[TaskNode]]]:
    grouped: Dict[Optional[UUID], List[List[TaskNode]]] = defaultdict(list)
    for cycle in cycles:
        # Prefer a specific vision_id if present; fall back to None.
        vision_id = next((node.vision_id for node in cycle if node.vision_id), None)
        grouped[vision_id].append(cycle)
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect parent-child cycles within the tasks table."
    )
    parser.add_argument(
        "--user-id", type=UUID, default=None, help="只检查指定用户的任务"
    )
    parser.add_argument(
        "--vision-id", type=UUID, default=None, help="只检查指定愿景下的任务"
    )
    parser.add_argument(
        "--include-deleted",
        action="store_true",
        help="包含已软删除的任务（默认忽略）",
    )
    args = parser.parse_args()

    tasks = _load_tasks(
        user_id=args.user_id,
        vision_id=args.vision_id,
        include_deleted=args.include_deleted,
    )

    if not tasks:
        print("未找到任务记录，确认筛选条件是否正确。")
        return

    cycles = _find_cycles(tasks)
    if not cycles:
        print("未检测到任务回路。")
        return

    grouped = _group_cycles_by_vision(cycles)
    total_cycles = sum(len(group) for group in grouped.values())
    print(f"检测到 {total_cycles} 个回路，涉及 {len(cycles)} 组任务。")
    print("-" * 80)

    for vision_id, vision_cycles in grouped.items():
        print(f"愿景: {vision_id or '未知/跨愿景'}")
        for idx, cycle in enumerate(vision_cycles, start=1):
            print(f"  回路 #{idx}（任务数: {len(cycle)}）")
            for node in cycle:
                content_excerpt = node.content.replace("\n", " ").strip()
                print(
                    f"    - Task {node.id} | parent={node.parent_id} | user={node.user_id} | 摘要: {content_excerpt}"
                )
            print("  " + "-" * 70)
        print("-" * 80)


if __name__ == "__main__":
    main()
