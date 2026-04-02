import { apiRequest } from "@/lib/api/client";
import {
  parsePaginatedListResponse,
  resolveNextPageWithFallback,
} from "@/lib/api/pagination";

const DEFAULT_PAGE_SIZE = 50;
type PageOptions = { page?: number; size?: number };

export type ScheduleCycleType =
  | "daily"
  | "weekly"
  | "monthly"
  | "interval"
  | "sequential";

export type DailyTimePoint = { time: string };
export type WeeklyTimePoint = { weekday: number; time: string };
export type MonthlyTimePoint = { day: number; time: string };
export type IntervalTimePoint = {
  minutes: number;
  start_at_local?: string;
  start_at_utc?: string;
};
export type SequentialTimePoint = {
  minutes: number;
};
export type ScheduleTimePoint =
  | DailyTimePoint
  | WeeklyTimePoint
  | MonthlyTimePoint
  | IntervalTimePoint
  | SequentialTimePoint;

export type ScheduledJob = {
  id: string;
  name: string;
  agent_id: string;
  prompt: string;
  cycle_type: ScheduleCycleType;
  time_point: ScheduleTimePoint | Record<string, unknown>;
  schedule_timezone: string;
  enabled: boolean;
  conversation_policy: "new_each_run" | "reuse_single";
  conversation_id?: string | null;
  is_running?: boolean;
  next_run_at_utc?: string | null;
  next_run_at_local?: string | null;
  last_run_at?: string | null;
  last_run_status?: "idle" | "success" | "failed" | null;
  status_summary: ScheduledJobStatusSummary;
  created_at: string;
  updated_at: string;
};

type ScheduledJobStatusSummary = {
  state: "idle" | "running" | "recent_failed";
  manual_intervention_recommended: boolean;
  running_started_at?: string | null;
  running_duration_seconds?: number | null;
  last_heartbeat_at?: string | null;
  heartbeat_age_seconds?: number | null;
  heartbeat_stale_after_seconds?: number | null;
  recent_failure_message?: string | null;
  recent_failure_error_code?: string | null;
  last_finished_at?: string | null;
};

export type ScheduledJobExecution = {
  id: string;
  task_id: string;
  status: "pending" | "running" | "success" | "failed";
  scheduled_for: string;
  started_at?: string | null;
  last_heartbeat_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  error_code?: string | null;
  response_content?: string | null;
  conversation_id?: string | null;
  user_message_id?: string | null;
  agent_message_id?: string | null;
  created_at?: string | null;
};

export type ScheduledJobPayload = {
  name: string;
  agent_id: string;
  prompt: string;
  cycle_type: ScheduleCycleType;
  time_point: ScheduleTimePoint;
  schedule_timezone: string;
  enabled: boolean;
  conversation_policy: "new_each_run" | "reuse_single";
};

type MarkScheduledJobFailedPayload = {
  reason?: string;
};

type ScheduledJobToggleResponse = {
  id: string;
  schedule_timezone: string;
  enabled: boolean;
  next_run_at_utc?: string | null;
  next_run_at_local?: string | null;
};

type ScheduledJobsListResponse =
  | ScheduledJob[]
  | { items: ScheduledJob[]; pagination?: unknown; meta?: unknown };

type ScheduledJobExecutionsListResponse =
  | ScheduledJobExecution[]
  | { items: ScheduledJobExecution[]; pagination?: unknown; meta?: unknown };

export const listScheduledJobsPage = async ({
  page = 1,
  size = DEFAULT_PAGE_SIZE,
}: PageOptions = {}) => {
  const response = await apiRequest<ScheduledJobsListResponse>(
    "/me/a2a/schedules",
    {
      query: { page, size },
    },
  );
  const parsed = parsePaginatedListResponse(response);
  const nextPage = resolveNextPageWithFallback({ parsed, page, size });

  return { ...parsed, nextPage };
};

export const getScheduledJob = (taskId: string) =>
  apiRequest<ScheduledJob>(`/me/a2a/schedules/${taskId}`);

export const createScheduledJob = (payload: ScheduledJobPayload) =>
  apiRequest<ScheduledJob, ScheduledJobPayload>("/me/a2a/schedules", {
    method: "POST",
    body: payload,
  });

export const updateScheduledJob = (
  jobId: string,
  payload: Partial<ScheduledJobPayload>,
) =>
  apiRequest<ScheduledJob, Partial<ScheduledJobPayload>>(
    `/me/a2a/schedules/${jobId}`,
    {
      method: "PATCH",
      body: payload,
    },
  );

export const enableScheduledJob = (jobId: string) =>
  apiRequest<ScheduledJobToggleResponse>(`/me/a2a/schedules/${jobId}/enable`, {
    method: "POST",
  });

export const disableScheduledJob = (jobId: string) =>
  apiRequest<ScheduledJobToggleResponse>(`/me/a2a/schedules/${jobId}/disable`, {
    method: "POST",
  });

export const markScheduledJobFailed = (
  jobId: string,
  payload: MarkScheduledJobFailedPayload = {},
) =>
  apiRequest<ScheduledJob, MarkScheduledJobFailedPayload>(
    `/me/a2a/schedules/${jobId}/mark-failed`,
    {
      method: "POST",
      body: payload,
    },
  );

export const deleteScheduledJob = (jobId: string) =>
  apiRequest<void>(`/me/a2a/schedules/${jobId}`, {
    method: "DELETE",
  });

export const listScheduledJobExecutionsPage = async (
  taskId: string,
  options?: { page?: number; size?: number },
) => {
  const page = options?.page ?? 1;
  const size = options?.size ?? DEFAULT_PAGE_SIZE;
  const response = await apiRequest<ScheduledJobExecutionsListResponse>(
    `/me/a2a/schedules/${taskId}/executions`,
    {
      query: {
        page,
        size,
      },
    },
  );

  const parsed = parsePaginatedListResponse(response);
  const nextPage = resolveNextPageWithFallback({ parsed, page, size });

  return { ...parsed, nextPage };
};
