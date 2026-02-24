import { act, create } from "react-test-renderer";

import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";
import { useSessionStore } from "@/store/session";

const mockCreateScheduledJob = jest.fn();
const mockGetScheduledJob = jest.fn();
const mockUpdateScheduledJob = jest.fn();
const mockInvalidateQueries = jest.fn();
const mockAllowNextNavigation = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockBackOrHome = jest.fn();
const mockBlurActiveElement = jest.fn();
const mockAgents = [
  {
    id: "agent-1",
    source: "personal",
    name: "Agent One",
    cardUrl: "https://example.com/card",
    status: "success",
  },
];

let capturedSubmit: (() => void) | null = null;
let capturedChange: ((patch: unknown) => void) | null = null;
let capturedAgentOptions: { id: string; name: string }[] = [];
let capturedTimeZone: string | undefined = undefined;

jest.mock("react-native/Libraries/Utilities/Dimensions", () => ({
  get: () => ({
    width: 360,
    height: 812,
    scale: 2,
    fontScale: 2,
  }),
  set: jest.fn(),
  addEventListener: () => ({
    remove: jest.fn(),
  }),
  removeEventListener: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({
    replace: jest.fn(),
    back: jest.fn(),
  }),
}));

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: mockAgents,
    isFetched: true,
  }),
}));

jest.mock("@/components/scheduled/ScheduledJobForm", () => ({
  ScheduledJobForm: ({
    onSubmit,
    onChange,
    agentOptions,
    timeZone,
  }: {
    agentOptions: { id: string; name: string }[];
    onSubmit: () => void;
    onChange: (patch: unknown) => void;
    timeZone?: string;
  }) => {
    capturedAgentOptions = agentOptions;
    capturedTimeZone = timeZone;
    capturedSubmit = onSubmit;
    capturedChange = onChange;
    return null;
  },
}));

jest.mock("@/components/layout/ScreenScrollView", () => ({
  ScreenScrollView: ({ children }: { children: unknown }) => children,
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: () => null,
}));

jest.mock("@/lib/api/client", () => {
  class ApiRequestError extends Error {
    status?: number;

    constructor(message: string, status?: number) {
      super(message);
      this.status = status;
    }
  }

  return {
    ApiRequestError,
  };
});

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: ({ rightElement }: { rightElement: unknown }) => rightElement,
}));

jest.mock("@/lib/api/scheduledJobs", () => ({
  createScheduledJob: (...args: unknown[]) => mockCreateScheduledJob(...args),
  getScheduledJob: (...args: unknown[]) => mockGetScheduledJob(...args),
  updateScheduledJob: (...args: unknown[]) => mockUpdateScheduledJob(...args),
}));

jest.mock("@/hooks/usePreventRemoveWhenDirty", () => ({
  usePreventRemoveWhenDirty: () => ({
    allowNextNavigation: mockAllowNextNavigation,
  }),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: () => mockBlurActiveElement(),
}));

jest.mock("@/lib/navigation", () => ({
  backOrHome: () => mockBackOrHome(),
}));

describe("ScheduledJobFormScreen", () => {
  beforeEach(() => {
    mockCreateScheduledJob.mockReset();
    mockGetScheduledJob.mockReset();
    mockUpdateScheduledJob.mockReset();
    mockInvalidateQueries.mockReset();
    mockAllowNextNavigation.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockBackOrHome.mockReset();
    mockBlurActiveElement.mockReset();
    capturedSubmit = null;
    capturedChange = null;
    capturedAgentOptions = [];
    capturedTimeZone = undefined;
    mockAgents.splice(0, mockAgents.length, {
      id: "agent-1",
      source: "personal",
      name: "Agent One",
      cardUrl: "https://example.com/card",
      status: "success",
    });
    act(() => {
      useSessionStore.setState({ user: null });
    });
  });

  it("does not keep dirty state lock after successfully creating a new job", async () => {
    mockCreateScheduledJob.mockResolvedValue({
      id: "job-1",
      name: "Daily Summary",
      agent_id: "agent-1",
      prompt: "Summarize status",
      cycle_type: "daily",
      time_point: { time: "07:00" },
      enabled: true,
    });

    await act(async () => {
      create(<ScheduledJobFormScreen />);
    });

    expect(capturedSubmit).toBeTruthy();
    expect(capturedChange).toBeTruthy();

    await act(async () => {
      capturedChange?.({
        agent_id: "agent-1",
        name: " Daily Summary ",
        prompt: "Summarize status for this week ",
      });
    });
    await act(async () => {
      await Promise.resolve();
      capturedSubmit?.();
      await Promise.resolve();
    });

    expect(mockCreateScheduledJob).toHaveBeenCalledTimes(1);
    expect(mockCreateScheduledJob).toHaveBeenCalledWith({
      name: "Daily Summary",
      agent_id: "agent-1",
      prompt: "Summarize status for this week",
      timezone: expect.any(String),
      cycle_type: "daily",
      time_point: { time: "07:00" },
      enabled: true,
      conversation_policy: "new_each_run",
    });
    expect(mockAllowNextNavigation).toHaveBeenCalledTimes(1);
  });

  it("normalizes interval minutes and converts start datetime on create", async () => {
    act(() => {
      useSessionStore.setState({
        user: {
          id: "user-1",
          email: "test@example.com",
          name: "Test User",
          is_superuser: false,
          timezone: "Asia/Shanghai",
        },
      });
    });

    mockCreateScheduledJob.mockResolvedValue({
      id: "job-1",
      name: "Interval Summary",
      agent_id: "agent-1",
      prompt: "Summarize status",
      cycle_type: "interval",
      time_point: { minutes: 5, start_at: "2026-02-22T01:30:00.000Z" },
      enabled: true,
    });
    const expectedStartAt = "2026-02-23T09:30";

    await act(async () => {
      create(<ScheduledJobFormScreen />);
    });

    expect(capturedSubmit).toBeTruthy();
    expect(capturedChange).toBeTruthy();

    await act(async () => {
      capturedChange?.({
        cycle_type: "interval",
        time_point: { minutes: 3, start_at: "2026-02-23 09:30" },
      });
    });
    await act(async () => {
      capturedChange?.({
        agent_id: "agent-1",
        name: "Interval Summary",
        prompt: "Summarize status for this week",
      });
    });

    await act(async () => {
      await Promise.resolve();
      capturedSubmit?.();
      await Promise.resolve();
    });

    expect(mockCreateScheduledJob).toHaveBeenCalledTimes(1);
    expect(mockCreateScheduledJob).toHaveBeenCalledWith({
      name: "Interval Summary",
      agent_id: "agent-1",
      prompt: "Summarize status for this week",
      timezone: "Asia/Shanghai",
      cycle_type: "interval",
      time_point: {
        minutes: 5,
        start_at: expectedStartAt,
      },
      enabled: true,
      conversation_policy: "new_each_run",
    });
    expect(capturedTimeZone).toBe("Asia/Shanghai");
  });

  it("rejects invalid interval start datetime", async () => {
    await act(async () => {
      create(<ScheduledJobFormScreen />);
    });

    expect(capturedSubmit).toBeTruthy();
    expect(capturedChange).toBeTruthy();

    await act(async () => {
      capturedChange?.({
        agent_id: "agent-1",
        name: "Interval Summary",
        prompt: "Summarize status",
      });
      await Promise.resolve();
    });

    await act(async () => {
      capturedChange?.({
        name: "Interval Summary",
        cycle_type: "interval",
        time_point: { minutes: 3, start_at: "bad-time" },
      });
      await Promise.resolve();
    });

    await act(async () => {
      capturedSubmit?.();
      await Promise.resolve();
    });

    expect(mockToastError).toHaveBeenCalledWith(
      "Validation failed",
      "Start datetime must be a valid date time.",
    );
    expect(mockCreateScheduledJob).not.toHaveBeenCalled();
  });

  it("filters shared agents out from the selectable list on scheduled job form", async () => {
    mockAgents.splice(
      0,
      mockAgents.length,
      {
        id: "agent-personal",
        source: "personal",
        name: "Personal Agent",
        cardUrl: "https://example.com/card-personal",
        status: "success",
      },
      {
        id: "agent-shared",
        source: "shared",
        name: "Shared Agent",
        cardUrl: "https://example.com/card-shared",
        status: "success",
      },
    );

    await act(async () => {
      create(<ScheduledJobFormScreen />);
    });

    expect(capturedAgentOptions).toEqual([
      { id: "agent-personal", name: "Personal Agent" },
    ]);
  });
});
