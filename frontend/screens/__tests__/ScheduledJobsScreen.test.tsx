import { act, create } from "react-test-renderer";

import { ScheduledJobsScreen } from "@/screens/ScheduledJobsScreen";

const mockToggleJobStatus = jest.fn();
const mockMarkJobFailed = jest.fn();
const mockRemoveJob = jest.fn();
const mockLoadFirstPage = jest.fn();
const mockLoadMore = jest.fn();
const mockExecutionLoadMore = jest.fn();
let mockJobs: any[] = [];

jest.mock("@/hooks/useScheduledJobs", () => ({
  useScheduledJobs: () => ({
    markJobFailed: mockMarkJobFailed,
    toggleJobStatus: mockToggleJobStatus,
    removeJob: mockRemoveJob,
  }),
}));

jest.mock("@/hooks/useScheduledJobsQuery", () => ({
  useScheduledJobsQuery: ({ enabled }: { enabled?: boolean }) => ({
    items: mockJobs,
    hasMore: false,
    loading: false,
    refreshing: false,
    loadingMore: false,
    loadFirstPage: mockLoadFirstPage.mockResolvedValue(true),
    loadMore: mockLoadMore,
  }),
}));

jest.mock("@/hooks/useScheduledJobExecutionsQuery", () => ({
  useScheduledJobExecutionsQuery: () => ({
    items: [],
    hasMore: false,
    loading: false,
    loadingMore: false,
    loadFirstPage: jest.fn(),
    loadMore: mockExecutionLoadMore,
  }),
}));

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: [],
    isFetched: true,
  }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({
    push: jest.fn(),
  }),
}));

jest.mock("@react-navigation/native", () => ({
  useFocusEffect: (cb: any) => cb(),
}));

let mockRenderedCardProps: any[] = [];
jest.mock("@/components/scheduled/ScheduledJobCard", () => ({
  ScheduledJobCard: (props: any) => {
    mockRenderedCardProps.push(props);
    return null;
  },
}));

jest.mock("@/components/layout/ScreenContainer", () => ({
  ScreenContainer: ({ children }: any) => children,
}));

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: () => null,
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: () => null,
}));

jest.mock("@/components/ui/Button", () => ({
  Button: () => null,
}));

describe("ScheduledJobsScreen sorting", () => {
  beforeEach(() => {
    mockRenderedCardProps = [];
    mockExecutionLoadMore.mockClear();
  });

  it("preserves backend order for scheduled jobs", async () => {
    mockJobs = [
      {
        id: "enabled-recent",
        enabled: true,
        last_run_status: "success",
        status_summary: {
          state: "idle",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T10:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "enabled-stale",
        enabled: true,
        last_run_status: "success",
        status_summary: {
          state: "idle",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T11:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "disabled-newest",
        enabled: false,
        last_run_status: "failed",
        status_summary: {
          state: "recent_failed",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T12:00:00Z",
        schedule_timezone: "UTC",
      },
    ];

    await act(async () => {
      create(<ScheduledJobsScreen />);
    });

    expect(mockRenderedCardProps.map(({ job }) => job.id)).toEqual([
      "enabled-recent",
      "enabled-stale",
      "disabled-newest",
    ]);
  });

  it("opens executions panel and loads more history from the rendered card", async () => {
    mockJobs = [
      {
        id: "job-with-executions",
        enabled: true,
        last_run_status: "success",
        status_summary: {
          state: "idle",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T10:00:00Z",
        schedule_timezone: "UTC",
      },
    ];

    await act(async () => {
      create(<ScheduledJobsScreen />);
    });

    await act(async () => {
      mockRenderedCardProps[0].onToggleExecutions();
    });

    const openCardProps = mockRenderedCardProps.at(-1);
    expect(openCardProps.executionsOpen).toBe(true);

    await act(async () => {
      await openCardProps.onLoadMoreExecutions();
    });

    expect(mockExecutionLoadMore).toHaveBeenCalledTimes(1);
  });
});
