import { useCallback } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { ApiRequestError } from "@/lib/api/client";
import {
  listScheduledJobsPage,
  type ScheduledJob,
} from "@/lib/api/scheduledJobs";
import { queryKeys } from "@/lib/queryKeys";

export function useScheduledJobsQuery(options?: { enabled?: boolean }) {
  const enabled = options?.enabled ?? true;

  const fetchPage = useCallback(async (page: number) => {
    const result = await listScheduledJobsPage({ page, size: 50 });
    return { items: result.items, nextPage: result.nextPage };
  }, []);

  const mapErrorMessage = useCallback((error: unknown) => {
    if (error instanceof ApiRequestError && error.status === 503) {
      return "A2A integration is disabled.";
    }
    return null;
  }, []);

  return usePaginatedList<ScheduledJob>({
    queryKey: queryKeys.sessions.scheduledJobs(),
    fetchPage,
    getKey: (item) => item.id,
    errorTitle: "Load jobs failed",
    fallbackMessage: "Load failed.",
    mapErrorMessage,
    enabled,
  });
}
