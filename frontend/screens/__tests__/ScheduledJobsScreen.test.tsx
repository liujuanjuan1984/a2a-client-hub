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
  useScheduledJobsQuery: ({ enabled: _enabled }: { enabled?: boolean }) => ({
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

jest.mock("react-native", () => {
  const React = jest.requireActual("react");
  const actual = jest.requireActual("react-native");

  const FlatList = ({
    data,
    renderItem,
    ListHeaderComponent,
    ListEmptyComponent,
    ListFooterComponent,
  }: any) => {
    const children: any[] = [];

    if (ListHeaderComponent) {
      children.push(ListHeaderComponent);
    }

    if (data?.length) {
      data.forEach((item: any, index: number) => {
        const element = renderItem?.({ item, index });
        if (element) {
          children.push(element);
        }
      });
    } else if (ListEmptyComponent) {
      children.push(ListEmptyComponent);
    }

    if (ListFooterComponent) {
      children.push(ListFooterComponent);
    }

    return React.createElement(React.Fragment, null, ...children);
  };

  const RefreshControl = () => null;

  return {
    ...actual,
    FlatList,
    RefreshControl,
  };
});

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
        id: "enabled-attention",
        enabled: true,
        is_running: true,
        status_summary: {
          state: "running",
          manual_intervention_recommended: true,
        },
        next_run_at_utc: "2026-02-23T10:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "enabled-running",
        enabled: true,
        is_running: true,
        status_summary: {
          state: "running",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T11:00:00Z",
        schedule_timezone: "UTC",
      },
      {
        id: "enabled-recent",
        enabled: true,
        last_run_status: "success",
        status_summary: {
          state: "idle",
          manual_intervention_recommended: false,
        },
        next_run_at_utc: "2026-02-23T12:00:00Z",
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
        next_run_at_utc: "2026-02-23T13:00:00Z",
        schedule_timezone: "UTC",
      },
    ];

    await act(async () => {
      create(<ScheduledJobsScreen />);
    });

    expect(mockRenderedCardProps.map(({ job }) => job.id)).toEqual([
      "enabled-attention",
      "enabled-running",
      "enabled-recent",
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
