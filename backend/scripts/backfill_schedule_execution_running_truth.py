#!/usr/bin/env python3
"""Drain legacy schedule task running-state columns before execution-truth migration.

This script must run against the pre-`4b6c6e0d8a2f` schema, before the migration
that drops `current_run_id`, `running_started_at`, and `last_heartbeat_at` from
`a2a_schedule_tasks`.

It performs a one-off reconciliation:
1. Find tasks still carrying legacy running-state projection.
2. Reuse a matching terminal execution when one already exists.
3. Otherwise fail the in-flight run by updating or inserting an execution row.
4. Clear the task-side running projection so the migration can proceed safely.

Default mode is dry-run. Pass `--apply` to mutate the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

BACKFILL_ERROR_MESSAGE = (
    "Execution backfilled as failed during schedule running-truth migration drain"
)
RUNNING_STATUS = "running"
SUCCESS_STATUS = "success"
FAILED_STATUS = "failed"
LEGACY_TASK_COLUMNS = {
    "current_run_id",
    "running_started_at",
    "last_heartbeat_at",
}
_SETTINGS: Any | None = None


@dataclass(frozen=True)
class BackfillStats:
    scanned: int = 0
    inserted_executions: int = 0
    failed_existing_executions: int = 0
    reused_terminal_executions: int = 0
    updated_tasks: int = 0

    def merge(
        self,
        *,
        scanned: int = 0,
        inserted_executions: int = 0,
        failed_existing_executions: int = 0,
        reused_terminal_executions: int = 0,
        updated_tasks: int = 0,
    ) -> "BackfillStats":
        return BackfillStats(
            scanned=self.scanned + scanned,
            inserted_executions=self.inserted_executions + inserted_executions,
            failed_existing_executions=(
                self.failed_existing_executions + failed_existing_executions
            ),
            reused_terminal_executions=(
                self.reused_terminal_executions + reused_terminal_executions
            ),
            updated_tasks=self.updated_tasks + updated_tasks,
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_settings() -> Any:
    global _SETTINGS
    if _SETTINGS is None:
        from app.core.config import settings as app_settings  # noqa: WPS433

        _SETTINGS = app_settings
    return _SETTINGS


def _ensure_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raise TypeError(f"Unsupported datetime value: {value!r}")


def _normalize_minutes(time_point: Any) -> int:
    if not isinstance(time_point, dict):
        return 5
    raw = time_point.get("minutes", time_point.get("interval_minutes"))
    if not isinstance(raw, int):
        return 5
    return max(5, min(1440, raw))


def _compute_sequential_next_run_at(
    *,
    time_point: Any,
    after_utc: datetime,
) -> datetime:
    return after_utc + timedelta(minutes=_normalize_minutes(time_point))


def _ensure_legacy_columns_present(connection: Connection) -> bool:
    settings = _get_settings()
    rows = connection.execute(
        text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = 'a2a_schedule_tasks'
            """),
        {"schema_name": settings.schema_name},
    ).scalars()
    task_columns = set(rows)
    return LEGACY_TASK_COLUMNS.issubset(task_columns)


def _legacy_task_rows(
    connection: Connection,
    *,
    lock_rows: bool,
    limit: int | None,
) -> list[dict[str, Any]]:
    settings = _get_settings()
    limit_clause = "LIMIT :limit" if limit is not None else ""
    lock_clause = "FOR UPDATE" if lock_rows else ""
    stmt = text(f"""
        SELECT
            id,
            user_id,
            conversation_id,
            cycle_type,
            time_point,
            enabled,
            next_run_at,
            consecutive_failures,
            last_run_status,
            current_run_id,
            running_started_at,
            last_heartbeat_at,
            delete_requested_at,
            deleted_at
        FROM {settings.schema_name}.a2a_schedule_tasks
        WHERE current_run_id IS NOT NULL
           OR running_started_at IS NOT NULL
           OR last_heartbeat_at IS NOT NULL
           OR last_run_status = :running_status
        ORDER BY updated_at ASC, id ASC
        {limit_clause}
        {lock_clause}
        """)
    params = {"running_status": RUNNING_STATUS}
    if limit is not None:
        params["limit"] = limit
    result = connection.execute(stmt, params)
    return [dict(row) for row in result.mappings().all()]


def _matching_execution(
    connection: Connection,
    *,
    task_id: UUID,
    run_id: UUID,
    lock_row: bool,
) -> dict[str, Any] | None:
    settings = _get_settings()
    lock_clause = "FOR UPDATE" if lock_row else ""
    result = connection.execute(
        text(f"""
            SELECT
                id,
                status,
                scheduled_for,
                started_at,
                finished_at,
                conversation_id
            FROM {settings.schema_name}.a2a_schedule_executions
            WHERE task_id = :task_id
              AND run_id = :run_id
            LIMIT 1
            {lock_clause}
            """),
        {"task_id": task_id, "run_id": run_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row is not None else None


def _task_projection_after_terminal(
    task_row: dict[str, Any],
    *,
    final_status: str,
    finished_at: datetime,
    failure_threshold: int,
    conversation_id: UUID | None,
) -> dict[str, Any]:
    enabled = bool(task_row["enabled"])
    next_run_at = _ensure_utc(task_row["next_run_at"])
    delete_requested_at = _ensure_utc(task_row["delete_requested_at"])
    deleted_at = _ensure_utc(task_row["deleted_at"])
    consecutive_failures = int(task_row["consecutive_failures"] or 0)

    if deleted_at is not None:
        enabled = False
        next_run_at = None
        delete_requested_at = None
    elif final_status == SUCCESS_STATUS:
        consecutive_failures = 0
    elif final_status == FAILED_STATUS:
        consecutive_failures += 1
        if consecutive_failures >= failure_threshold:
            enabled = False
    else:
        raise ValueError(f"Unsupported terminal status: {final_status}")

    if delete_requested_at is not None:
        deleted_at = finished_at
        enabled = False
        next_run_at = None
        delete_requested_at = None
    elif task_row["cycle_type"] == "sequential":
        next_run_at = (
            _compute_sequential_next_run_at(
                time_point=task_row["time_point"],
                after_utc=finished_at,
            )
            if enabled
            else None
        )

    return {
        "last_run_status": final_status,
        "last_run_at": finished_at,
        "consecutive_failures": consecutive_failures,
        "enabled": enabled,
        "next_run_at": next_run_at,
        "delete_requested_at": delete_requested_at,
        "deleted_at": deleted_at,
        "conversation_id": conversation_id or task_row["conversation_id"],
    }


def _apply_task_projection(
    connection: Connection,
    *,
    task_id: UUID,
    projection: dict[str, Any],
) -> None:
    settings = _get_settings()
    connection.execute(
        text(f"""
            UPDATE {settings.schema_name}.a2a_schedule_tasks
            SET
                last_run_status = :last_run_status,
                last_run_at = :last_run_at,
                consecutive_failures = :consecutive_failures,
                enabled = :enabled,
                next_run_at = :next_run_at,
                delete_requested_at = :delete_requested_at,
                deleted_at = :deleted_at,
                conversation_id = :conversation_id,
                current_run_id = NULL,
                running_started_at = NULL,
                last_heartbeat_at = NULL,
                updated_at = now()
            WHERE id = :task_id
            """),
        {"task_id": task_id, **projection},
    )


def _fail_existing_execution(
    connection: Connection,
    *,
    execution_id: UUID,
    started_at: datetime,
    finished_at: datetime,
    conversation_id: UUID | None,
) -> None:
    settings = _get_settings()
    connection.execute(
        text(f"""
            UPDATE {settings.schema_name}.a2a_schedule_executions
            SET
                started_at = COALESCE(started_at, :started_at),
                finished_at = :finished_at,
                status = :status,
                error_message = :error_message,
                conversation_id = COALESCE(conversation_id, :conversation_id),
                updated_at = now()
            WHERE id = :execution_id
            """),
        {
            "execution_id": execution_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": FAILED_STATUS,
            "error_message": BACKFILL_ERROR_MESSAGE,
            "conversation_id": conversation_id,
        },
    )


def _insert_failed_execution(
    connection: Connection,
    *,
    task_row: dict[str, Any],
    run_id: UUID,
    scheduled_for: datetime,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    settings = _get_settings()
    connection.execute(
        text(f"""
            INSERT INTO {settings.schema_name}.a2a_schedule_executions (
                id,
                user_id,
                task_id,
                run_id,
                scheduled_for,
                started_at,
                finished_at,
                status,
                error_message,
                response_content,
                conversation_id,
                user_message_id,
                agent_message_id
            ) VALUES (
                :id,
                :user_id,
                :task_id,
                :run_id,
                :scheduled_for,
                :started_at,
                :finished_at,
                :status,
                :error_message,
                NULL,
                :conversation_id,
                NULL,
                NULL
            )
            ON CONFLICT (task_id, run_id) DO NOTHING
            """),
        {
            "id": uuid4(),
            "user_id": task_row["user_id"],
            "task_id": task_row["id"],
            "run_id": run_id,
            "scheduled_for": scheduled_for,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": FAILED_STATUS,
            "error_message": BACKFILL_ERROR_MESSAGE,
            "conversation_id": task_row["conversation_id"],
        },
    )


def _process_one_task(
    connection: Connection,
    *,
    task_row: dict[str, Any],
    apply_changes: bool,
    now_utc: datetime,
    failure_threshold: int,
) -> BackfillStats:
    stats = BackfillStats(scanned=1)
    run_id = task_row["current_run_id"] or uuid4()
    running_started_at = _ensure_utc(task_row["running_started_at"])
    last_heartbeat_at = _ensure_utc(task_row["last_heartbeat_at"])
    next_run_at = _ensure_utc(task_row["next_run_at"])
    started_at = running_started_at or last_heartbeat_at or next_run_at or now_utc
    scheduled_for = next_run_at or started_at

    execution_row = None
    if task_row["current_run_id"] is not None:
        execution_row = _matching_execution(
            connection,
            task_id=task_row["id"],
            run_id=task_row["current_run_id"],
            lock_row=apply_changes,
        )

    final_status = FAILED_STATUS
    finished_at = now_utc
    conversation_id = task_row["conversation_id"]

    if execution_row is not None and execution_row["status"] in {
        SUCCESS_STATUS,
        FAILED_STATUS,
    }:
        final_status = execution_row["status"]
        finished_at = _ensure_utc(execution_row["finished_at"]) or now_utc
        conversation_id = execution_row["conversation_id"] or conversation_id
        stats = stats.merge(reused_terminal_executions=1)
    elif execution_row is not None:
        conversation_id = execution_row["conversation_id"] or conversation_id
        if apply_changes:
            _fail_existing_execution(
                connection,
                execution_id=execution_row["id"],
                started_at=started_at,
                finished_at=finished_at,
                conversation_id=conversation_id,
            )
        stats = stats.merge(failed_existing_executions=1)
    else:
        if apply_changes:
            _insert_failed_execution(
                connection,
                task_row=task_row,
                run_id=run_id,
                scheduled_for=scheduled_for,
                started_at=started_at,
                finished_at=finished_at,
            )
        stats = stats.merge(inserted_executions=1)

    projection = _task_projection_after_terminal(
        task_row,
        final_status=final_status,
        finished_at=finished_at,
        failure_threshold=failure_threshold,
        conversation_id=conversation_id,
    )
    if apply_changes:
        _apply_task_projection(
            connection,
            task_id=task_row["id"],
            projection=projection,
        )
    return stats.merge(updated_tasks=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill legacy schedule task running-state columns into execution rows "
            "before revision 4b6c6e0d8a2f."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reconciliation instead of running in dry-run mode",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optionally process only the first N legacy tasks",
    )
    return parser.parse_args()


def _print_summary(
    *,
    mode: str,
    stats: BackfillStats,
    sample_ids: list[UUID],
) -> None:
    settings = _get_settings()
    print(f"Mode: {mode}")
    print(f"Schema: {settings.schema_name}")
    print(f"Legacy tasks scanned: {stats.scanned}")
    print(f"Tasks projected to terminal state: {stats.updated_tasks}")
    print(f"Existing executions failed: {stats.failed_existing_executions}")
    print(f"Terminal executions reused: {stats.reused_terminal_executions}")
    print(f"Missing executions inserted: {stats.inserted_executions}")
    if sample_ids:
        print("Sample task ids:")
        for task_id in sample_ids[:10]:
            print(f"  - {task_id}")


def main() -> None:
    args = parse_args()
    settings = _get_settings()
    safe_url = make_url(settings.app_database_url_for_alembic).render_as_string(
        hide_password=True
    )
    print(f"Database URL: {safe_url}")
    print(
        "This script must be run before applying revision 4b6c6e0d8a2f "
        "and after draining old scheduler workers."
    )

    engine = create_engine(settings.app_database_url_for_alembic)
    failure_threshold = max(int(settings.a2a_schedule_task_failure_threshold), 1)
    mode = "apply" if args.apply else "dry-run"

    with engine.begin() if args.apply else engine.connect() as connection:
        if not _ensure_legacy_columns_present(connection):
            print(
                "Legacy task running-state columns are already absent. "
                "Nothing to backfill."
            )
            return

        task_rows = _legacy_task_rows(
            connection,
            lock_rows=args.apply,
            limit=args.limit,
        )
        stats = BackfillStats()
        sample_ids = [row["id"] for row in task_rows]

        for task_row in task_rows:
            stats = stats.merge(
                **_process_one_task(
                    connection,
                    task_row=task_row,
                    apply_changes=args.apply,
                    now_utc=_utc_now(),
                    failure_threshold=failure_threshold,
                ).__dict__
            )

        _print_summary(mode=mode, stats=stats, sample_ids=sample_ids)

        if not args.apply:
            print("Dry-run only. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
