# Ops: Scheduler Recovery and Best Practices

This document outlines the standard operating procedures (SOP) for recovering the A2A Scheduled Tasks execution engine after abnormal terminations (such as OOM kills, ungraceful process restarts, or extended database outages).

## 1. Context and Problem

A2A Scheduled Tasks are tracked with states (e.g., `pending`, `running`, `success`, `failed`). When an execution is claimed by a worker, the `status` of `A2AScheduleExecution` and `last_run_status` of `A2AScheduleTask` are set to `running`.

If the backend process is killed or restarted abruptly while a task is `running`, the status might never be updated to `failed` or `success`. These stale `running` states can:
1. Block subsequent scheduling for the affected tasks.
2. Consume global or per-user concurrency quotas, eventually halting all scheduling capabilities.

The system has auto-recovery features, but these depend on configured timeout thresholds. In critical outages, manual intervention might be required to restore service quickly.

## 2. Parameter Tuning Baseline

To minimize the impact of "stuck" states, tune the following `.env` parameters based on your deployment's characteristics:

- **`A2A_SCHEDULE_TASK_STREAM_IDLE_TIMEOUT`**: Defines how long to wait for upstream A2A streaming chunks.
  - *Recommendation*: **60 to 120 seconds**. If a stream hangs for this long without data, it is considered dead.
- **`A2A_SCHEDULE_TASK_INVOKE_TIMEOUT`**: The absolute maximum execution time allowed for a single scheduled run.
  - *Recommendation*: Default is 3600s, but it is highly recommended to **reduce this to your actual expected max task duration** (e.g., 600s or 1200s). A shorter timeout allows the auto-recovery mechanism to clear stale tasks much faster after a crash.

## 3. Recommended Restart Procedure

To prevent tasks from being forcefully terminated mid-execution:

1. **Graceful Shutdown**: Always attempt a SIGTERM before SIGKILL. The application's lifespan manager will try to finalize active streams gracefully if given sufficient time.
2. **Maintenance Window**: If deploying large changes or performing database maintenance, temporarily pause the scheduling worker if possible (or stop the worker instances prior to updating the database).

## 4. Emergency Recovery (Manual Intervention)

If the system was ungracefully restarted and a large number of tasks are stuck in `running` state blocking the queue, follow these steps to manually recover them.

### Option A: Using the CLI Tool (Recommended)

The backend provides a dedicated script to safely mark stale `running` tasks as `failed`.

```bash
# Run the script from the backend directory
cd backend/

# Run the cleanup command with a threshold (in seconds)
# e.g., to clear tasks running longer than 3600 seconds (1 hour):
uv run scripts/clean_stale_tasks.py --threshold 3600
```

### Option B: Emergency SQL Recovery

If the CLI tool is unavailable or you need to clear the states directly via database console (e.g., `psql`), execute the following atomic transactions. Ensure you adjust the `3600 seconds` interval to fit your needs.

```sql
BEGIN;

-- 1. Recover Task Definitions
UPDATE a2a_client_hub_schema.a2a_schedule_tasks
SET last_run_status = 'failed',
    last_run_at = NOW()
WHERE last_run_status = 'running'
  AND last_run_at <= NOW() - INTERVAL '3600 seconds';

-- 2. Recover Execution Records
UPDATE a2a_client_hub_schema.a2a_schedule_executions
SET status = 'failed',
    finished_at = NOW(),
    error_message = 'Recovered after restart or timeout'
WHERE status = 'running'
  AND finished_at IS NULL
  AND started_at <= NOW() - INTERVAL '3600 seconds';

COMMIT;
```

> **Warning:** Do not set the threshold too low, or you risk killing actively processing, legitimate tasks.
