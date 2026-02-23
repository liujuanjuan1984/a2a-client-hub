import { apiRequest } from "@/lib/api/client";
import { parsePaginatedListResponse } from "@/lib/api/pagination";

const DEFAULT_PAGE_SIZE = 50;
type PageOptions = { page?: number; size?: number };

export type ScheduleCycleType = "daily" | "weekly" | "monthly" | "interval";

export type DailyTimePoint = { time: string };
export type WeeklyTimePoint = { weekday: number; time: string };
export type MonthlyTimePoint = { day: number; time: string };
export type IntervalTimePoint = { minutes: number; start_at?: string };
export type ScheduleTimePoint =
  | DailyTimePoint
  | WeeklyTimePoint
  | MonthlyTimePoint
  | IntervalTimePoint;

export type ScheduledJob = {
  id: string;
  name: string;
  agent_id: string;
  prompt: string;
  cycle_type: ScheduleCycleType;
  time_point: ScheduleTimePoint | Record<string, unknown>;
  enabled: boolean;
  conversation_id?: string | null;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_run_status?: "idle" | "running" | "success" | "failed" | null;
  created_at: string;
  updated_at: string;
};

export type ScheduledJobExecution = {
  id: string;
  task_id: string;
  status: "running" | "success" | "failed";
  scheduled_for: string;
  started_at: string;
  finished_at?: string | null;
  error_message?: string | null;
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
  enabled: boolean;
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

  // Backward-compatible heuristic when the backend doesn't send pagination.
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : parsed.items.length >= size
        ? page + 1
        : undefined;

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
  apiRequest<void>(`/me/a2a/schedules/${jobId}/enable`, {
    method: "POST",
  });

export const disableScheduledJob = (jobId: string) =>
  apiRequest<void>(`/me/a2a/schedules/${jobId}/disable`, {
    method: "POST",
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

  // Backward-compatible heuristic when the backend doesn't send pagination.
  const nextPage =
    typeof parsed.nextPage === "number"
      ? parsed.nextPage
      : parsed.items.length >= size
        ? page + 1
        : undefined;

  return { ...parsed, nextPage };
};
