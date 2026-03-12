import { act, create } from "react-test-renderer";

import { ScheduledJobsScreen } from "@/screens/ScheduledJobsScreen";

const mockToggleJobStatus = jest.fn();
const mockMarkJobFailed = jest.fn();
const mockRemoveJob = jest.fn();
const mockLoadFirstPage = jest.fn();
const mockLoadMore = jest.fn();
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
    loadMore: jest.fn(),
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

let mockRenderedCards: any[] = [];
jest.mock("@/components/scheduled/ScheduledJobCard", () => ({
  ScheduledJobCard: ({ job }: any) => {
    mockRenderedCards.push(job);
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
    mockRenderedCards = [];
  });

  it("sorts jobs according to priority: enabled > running > next_run_at", async () => {
    mockJobs = [
      {
        id: "1",
        enabled: false,
        last_run_status: "failed",
        next_run_at_utc: "2026-02-23T10:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "2",
        enabled: true,
        is_running: true,
        last_run_status: "success",
        next_run_at_utc: "2026-02-23T11:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "3",
        enabled: true,
        last_run_status: "success",
        next_run_at_utc: "2026-02-23T09:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "4",
        enabled: true,
        last_run_status: "success",
        next_run_at_utc: "2026-02-23T12:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "5",
        enabled: false,
        is_running: true,
        last_run_status: "failed",
        next_run_at_utc: "2026-02-23T08:00:00Z",
        schedule_timezone: "UTC",
      },
    ];

    await act(async () => {
      create(<ScheduledJobsScreen />);
    });

    expect(mockRenderedCards.map((j) => j.id)).toEqual([
      "2",
      "3",
      "4",
      "1",
      "5",
    ]);
  });
});
