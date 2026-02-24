import { useCallback } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import {
  listScheduledJobExecutionsPage,
  type ScheduledJobExecution,
} from "@/lib/api/scheduledJobs";
import { queryKeys } from "@/lib/queryKeys";

export function useScheduledJobExecutionsQuery(options: {
  taskId?: string;
  enabled: boolean;
}) {
  const { taskId, enabled } = options;

  const fetchPage = useCallback(
    async (page: number) => {
      if (!taskId) {
        throw new Error("Task id is required.");
      }
      const result = await listScheduledJobExecutionsPage(taskId, {
        page,
        size: 50,
      });
      return { items: result.items, nextPage: result.nextPage };
    },
    [taskId],
  );

  return usePaginatedList<ScheduledJobExecution>({
    queryKey: queryKeys.schedules.executions(taskId ?? "missing"),
    fetchPage,
    getKey: (item) => item.id,
    errorTitle: "Load executions failed",
    fallbackMessage: "Load failed.",
    enabled: enabled && Boolean(taskId),
  });
}
