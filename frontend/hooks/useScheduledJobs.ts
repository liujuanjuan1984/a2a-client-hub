import { useCallback } from "react";

import {
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

  return {
    toggleJobStatus,
  };
}
