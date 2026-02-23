import { useCallback } from "react";

import {
  disableScheduledJob,
  enableScheduledJob,
  markScheduledJobFailed,
  type ScheduledJob,
} from "@/lib/api/scheduledJobs";

export function useScheduledJobs() {
  const toggleJobStatus = useCallback(async (job: ScheduledJob) => {
    if (job.enabled) {
      await disableScheduledJob(job.id);
      return;
    }
    await enableScheduledJob(job.id);
  }, []);

  const markJobFailed = useCallback(
    async (job: ScheduledJob, reason?: string) => {
      await markScheduledJobFailed(job.id, { reason });
    },
    [],
  );

  return {
    markJobFailed,
    toggleJobStatus,
  };
}
