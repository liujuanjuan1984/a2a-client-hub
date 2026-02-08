import { useCallback, useState } from "react";

import {
  disableScheduledJob,
  enableScheduledJob,
  listScheduledJobExecutionsPage,
  type ScheduledJob,
  type ScheduledJobExecution,
} from "@/lib/api/scheduledJobs";

const mergeUniqueById = <T extends { id: string }>(prev: T[], next: T[]) => {
  const map = new Map<string, T>();
  prev.forEach((item) => map.set(item.id, item));
  next.forEach((item) => map.set(item.id, item));
  return Array.from(map.values());
};

export function useScheduledJobs() {
  const [executionsByTaskId, setExecutionsByTaskId] = useState<
    Record<string, ScheduledJobExecution[]>
  >({});
  const [executionsNextPageByTaskId, setExecutionsNextPageByTaskId] = useState<
    Record<string, number | null>
  >({});
  const [loadingExecutionsTaskId, setLoadingExecutionsTaskId] = useState<
    string | null
  >(null);
  const [loadingMoreExecutionsTaskId, setLoadingMoreExecutionsTaskId] =
    useState<string | null>(null);

  const toggleJobStatus = useCallback(async (job: ScheduledJob) => {
    if (job.enabled) {
      await disableScheduledJob(job.id);
      return;
    }
    await enableScheduledJob(job.id);
  }, []);

  const loadExecutions = useCallback(async (taskId: string) => {
    setLoadingExecutionsTaskId(taskId);
    try {
      const result = await listScheduledJobExecutionsPage(taskId, {
        page: 1,
        size: 50,
      });
      setExecutionsByTaskId((prev) => ({ ...prev, [taskId]: result.items }));
      setExecutionsNextPageByTaskId((prev) => ({
        ...prev,
        [taskId]: typeof result.nextPage === "number" ? result.nextPage : null,
      }));
      return result.items;
    } finally {
      setLoadingExecutionsTaskId(null);
    }
  }, []);

  const loadMoreExecutions = useCallback(
    async (taskId: string) => {
      const nextPage = executionsNextPageByTaskId[taskId];
      if (typeof nextPage !== "number") {
        return executionsByTaskId[taskId] ?? [];
      }
      setLoadingMoreExecutionsTaskId(taskId);
      try {
        const result = await listScheduledJobExecutionsPage(taskId, {
          page: nextPage,
          size: 50,
        });
        setExecutionsByTaskId((prev) => {
          const current = prev[taskId] ?? [];
          return {
            ...prev,
            [taskId]: mergeUniqueById(current, result.items),
          };
        });
        setExecutionsNextPageByTaskId((prev) => ({
          ...prev,
          [taskId]:
            typeof result.nextPage === "number" ? result.nextPage : null,
        }));
        return result.items;
      } finally {
        setLoadingMoreExecutionsTaskId(null);
      }
    },
    [executionsByTaskId, executionsNextPageByTaskId],
  );

  return {
    executionsByTaskId,
    executionsNextPageByTaskId,
    loadingExecutionsTaskId,
    loadingMoreExecutionsTaskId,
    loadExecutions,
    loadMoreExecutions,
    toggleJobStatus,
  };
}
