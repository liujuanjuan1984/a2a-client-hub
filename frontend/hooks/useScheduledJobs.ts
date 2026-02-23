import { useCallback } from "react";

import {
  failScheduledJob,
  disableScheduledJob,
  enableScheduledJob,
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

  const markJobFailed = useCallback(async (job: ScheduledJob) => {
    if (job.last_run_status !== "running") return;
    await failScheduledJob(job.id);
  }, []);

  return {
    markJobFailed,
    toggleJobStatus,
  };
}
