#!/usr/bin/env python3
"""Cleanup script for stale running A2A scheduled tasks.

This script recovers tasks and executions that are stuck in a "running" state
due to abnormal service termination (e.g., OOM, ungraceful restart).
Run this manually or via a cronjob if long-hanging running tasks are blocking the schedule.

Usage:
  python backend/scripts/clean_stale_tasks.py [--threshold SECONDS]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta

from sqlalchemy import func, update

# Ensure we can import the FastAPI app package when executed from anywhere.
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.db.models import A2AScheduleExecution, A2AScheduleTask  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402


async def clean_stale_tasks(threshold_seconds: int) -> tuple[int, int]:
    """
    Recover stale tasks and executions that have been 'running' longer than threshold.
    Returns a tuple of (tasks_recovered_count, executions_recovered_count).
    """
    async with AsyncSessionLocal() as session:
        # 1. Recover Task State
        # If last_run_at is too old, set last_run_status to failed.
        stmt_tasks = (
            update(A2AScheduleTask)
            .where(
                A2AScheduleTask.last_run_status == "running",
                A2AScheduleTask.last_run_at
                <= func.now() - timedelta(seconds=threshold_seconds),
            )
            .values(last_run_status="failed", last_run_at=func.now())
        )
        result_tasks = await session.execute(stmt_tasks)
        tasks_updated = result_tasks.rowcount

        # 2. Recover Execution Records
        # If started_at is too old and not finished, mark as failed.
        stmt_execs = (
            update(A2AScheduleExecution)
            .where(
                A2AScheduleExecution.status == "running",
                A2AScheduleExecution.finished_at.is_(None),
                A2AScheduleExecution.started_at
                <= func.now() - timedelta(seconds=threshold_seconds),
            )
            .values(
                status="failed",
                finished_at=func.now(),
                error_message="Recovered after restart or timeout",
            )
        )
        result_execs = await session.execute(stmt_execs)
        execs_updated = result_execs.rowcount

        await session.commit()
        return tasks_updated, execs_updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clean stale A2A scheduled tasks and executions after a restart or crash."
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=3600,
        help="Threshold in seconds to consider a 'running' task as stale (default: 3600)",
    )
    args = parser.parse_args()

    print(
        f"🔍 Starting cleanup for tasks running longer than {args.threshold} seconds..."
    )

    try:
        tasks_recovered, execs_recovered = asyncio.run(
            clean_stale_tasks(args.threshold)
        )
        print(f"✅ Successfully recovered {tasks_recovered} stale tasks.")
        print(f"✅ Successfully recovered {execs_recovered} stale executions.")
    except Exception as e:
        print(f"❌ Error during cleanup: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
