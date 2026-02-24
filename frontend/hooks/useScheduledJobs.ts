import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  disableScheduledJob,
  enableScheduledJob,
  markScheduledJobFailed,
  type ScheduledJob,
} from "@/lib/api/scheduledJobs";
import { queryKeys } from "@/lib/queryKeys";

export function useScheduledJobs() {
  const queryClient = useQueryClient();

  const toggleJobStatus = useCallback(
    async (job: ScheduledJob) => {
      if (job.enabled) {
        await disableScheduledJob(job.id);
      } else {
        await enableScheduledJob(job.id);
      }
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.schedules.listRoot(),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.schedules.executionsRoot(job.id),
        }),
      ]);
    },
    [queryClient],
  );

  const markJobFailed = useCallback(
    async (job: ScheduledJob, reason?: string) => {
      await markScheduledJobFailed(job.id, { reason });
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: queryKeys.schedules.listRoot(),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.schedules.executionsRoot(job.id),
        }),
      ]);
    },
    [queryClient],
  );

  return {
    markJobFailed,
    toggleJobStatus,
  };
}
