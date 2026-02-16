import { act, create } from "react-test-renderer";

import { ScheduledJobFormScreen } from "@/screens/ScheduledJobFormScreen";

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
  }: {
    agentOptions: { id: string; name: string }[];
    onSubmit: () => void;
    onChange: (patch: unknown) => void;
  }) => {
    capturedAgentOptions = agentOptions;
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
    mockAgents.splice(0, mockAgents.length, {
      id: "agent-1",
      source: "personal",
      name: "Agent One",
      cardUrl: "https://example.com/card",
      status: "success",
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
      cycle_type: "daily",
      time_point: { time: "07:00" },
      enabled: true,
    });
    expect(mockAllowNextNavigation).toHaveBeenCalledTimes(1);
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
