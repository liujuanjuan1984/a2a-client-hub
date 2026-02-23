import { renderHook } from "@testing-library/react-native";

import { useScheduledJobs } from "@/hooks/useScheduledJobs";
import {
  disableScheduledJob,
  enableScheduledJob,
  markScheduledJobFailed,
} from "@/lib/api/scheduledJobs";

jest.mock("@/lib/api/scheduledJobs", () => ({
  disableScheduledJob: jest.fn(),
  enableScheduledJob: jest.fn(),
  markScheduledJobFailed: jest.fn(),
}));

describe("useScheduledJobs", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("toggles enabled job to disabled", async () => {
    const { result } = renderHook(() => useScheduledJobs());

    await result.current.toggleJobStatus({
      id: "job-1",
      enabled: true,
    } as any);

    expect(disableScheduledJob).toHaveBeenCalledWith("job-1");
    expect(enableScheduledJob).not.toHaveBeenCalled();
  });

  it("toggles disabled job to enabled", async () => {
    const { result } = renderHook(() => useScheduledJobs());

    await result.current.toggleJobStatus({
      id: "job-2",
      enabled: false,
    } as any);

    expect(enableScheduledJob).toHaveBeenCalledWith("job-2");
    expect(disableScheduledJob).not.toHaveBeenCalled();
  });

  it("marks a job as failed with reason", async () => {
    const { result } = renderHook(() => useScheduledJobs());

    await result.current.markJobFailed(
      {
        id: "job-3",
      } as any,
      "Manual stop from scheduled jobs UI",
    );

    expect(markScheduledJobFailed).toHaveBeenCalledWith("job-3", {
      reason: "Manual stop from scheduled jobs UI",
    });
  });
});
