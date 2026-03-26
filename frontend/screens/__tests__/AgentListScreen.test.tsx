import { act, create } from "react-test-renderer";

import { AgentListScreen } from "@/screens/AgentListScreen";

const mockPush = jest.fn();
const mockSetActiveAgent = jest.fn();
const mockInvalidateQueries = jest.fn(() => Promise.resolve());
const mockBatchMutate = jest.fn();
const mockCheckAgentHealth = jest.fn((_agentId: string, _force?: boolean) =>
  Promise.resolve({}),
);
const mockBlurActiveElement = jest.fn();

let mockButtons: Record<string, unknown>[] = [];

jest.mock("@tanstack/react-query", () => ({
  useMutation: () => ({
    isPending: false,
    mutate: mockBatchMutate,
  }),
  useQueryClient: () => ({
    invalidateQueries: mockInvalidateQueries,
  }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({
    push: mockPush,
  }),
}));

jest.mock("@/hooks/useAgentListQueries", () => ({
  usePersonalAgentsListQuery: ({ healthBucket }: { healthBucket: string }) => {
    if (healthBucket === "attention") {
      return {
        data: {
          items: [
            {
              id: "personal-attention-1",
              name: "Attention Agent",
              card_url: "https://example.com/attention.json",
              auth_type: "none",
              enabled: true,
              health_status: "degraded",
              consecutive_health_check_failures: 1,
              last_health_check_at: "2026-03-25T10:00:00.000Z",
              last_successful_health_check_at: null,
              last_health_check_error: "Connection failed",
              tags: [],
              extra_headers: {},
              created_at: "2026-03-25T09:00:00.000Z",
              updated_at: "2026-03-25T09:00:00.000Z",
            },
          ],
          pagination: { page: 1, size: 12, total: 1, pages: 1 },
          meta: {
            counts: { healthy: 1, degraded: 1, unavailable: 0, unknown: 1 },
          },
        },
        isFetching: false,
        refetch: jest.fn().mockResolvedValue({ error: null }),
      };
    }

    return {
      data: {
        items: [
          {
            id: "personal-healthy-1",
            name: "Healthy Agent",
            card_url: "https://example.com/healthy.json",
            auth_type: "none",
            enabled: true,
            health_status: "healthy",
            consecutive_health_check_failures: 0,
            last_health_check_at: "2026-03-25T09:00:00.000Z",
            last_successful_health_check_at: "2026-03-25T09:00:00.000Z",
            last_health_check_error: null,
            tags: [],
            extra_headers: {},
            created_at: "2026-03-25T08:00:00.000Z",
            updated_at: "2026-03-25T08:00:00.000Z",
          },
        ],
        pagination: { page: 1, size: 12, total: 1, pages: 1 },
        meta: {
          counts: { healthy: 1, degraded: 1, unavailable: 0, unknown: 1 },
        },
      },
      isFetching: false,
      refetch: jest.fn().mockResolvedValue({ error: null }),
    };
  },
  useSharedAgentsListQuery: () => ({
    data: {
      items: [
        {
          id: "shared-1",
          name: "Shared Agent",
          card_url: "https://example.com/shared.json",
          tags: [],
        },
      ],
      pagination: { page: 1, size: 8, total: 1, pages: 1 },
      meta: {},
    },
    isFetching: false,
    refetch: jest.fn().mockResolvedValue({ error: null }),
  }),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  checkAgentHealth: (agentId: string, force?: boolean) =>
    mockCheckAgentHealth(agentId, force),
  checkAgentsHealth: jest.fn(),
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: () => mockBlurActiveElement(),
}));

jest.mock("@/store/agents", () => ({
  useAgentStore: (
    selector: (state: { setActiveAgent: typeof mockSetActiveAgent }) => unknown,
  ) => selector({ setActiveAgent: mockSetActiveAgent }),
}));

jest.mock("@/store/chat", () => ({
  useChatStore: Object.assign(() => null, {
    getState: () => ({
      getLatestConversationIdByAgentId: () => null,
      generateConversationId: () => "conv-generated-1",
    }),
  }),
}));

jest.mock("@/store/session", () => ({
  useSessionStore: (
    selector: (state: { user: { is_superuser: boolean } }) => unknown,
  ) => selector({ user: { is_superuser: true } }),
}));

jest.mock("@/components/layout/ScreenContainer", () => ({
  ScreenContainer: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: ({ rightElement }: { rightElement?: React.ReactNode }) =>
    rightElement ?? null,
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: () => null,
}));

jest.mock("@/components/ui/Button", () => ({
  Button: (props: Record<string, unknown>) => {
    mockButtons.push(props);
    return null;
  },
}));

describe("AgentListScreen", () => {
  beforeEach(() => {
    mockButtons = [];
    jest.clearAllMocks();
  });

  it("renders paginated sections and handles list actions", async () => {
    await act(async () => {
      create(<AgentListScreen />);
    });

    expect(
      mockButtons.some((button) => button.label === "Check availability"),
    ).toBe(true);
    expect(mockButtons.some((button) => button.label === "Expand")).toBe(true);
    expect(mockButtons.some((button) => button.label === "Details")).toBe(true);

    const checkButton = mockButtons.find(
      (button) => button.label === "Check",
    ) as { onPress: () => Promise<void> };
    await act(async () => {
      await checkButton.onPress();
    });

    expect(mockCheckAgentHealth).toHaveBeenCalledWith(
      "personal-healthy-1",
      true,
    );
    expect(mockInvalidateQueries).toHaveBeenCalled();

    const chatButton = mockButtons.find(
      (button) => button.label === "Chat",
    ) as { onPress: () => void };
    await act(async () => {
      chatButton.onPress();
    });

    expect(mockSetActiveAgent).toHaveBeenCalledWith("personal-healthy-1");
    expect(mockPush).toHaveBeenCalled();
    expect(mockBlurActiveElement).toHaveBeenCalled();

    const batchButton = mockButtons.find(
      (button) => button.label === "Check availability",
    ) as { onPress: () => void };
    await act(async () => {
      batchButton.onPress();
    });

    expect(mockBatchMutate).toHaveBeenCalled();

    const expandButton = mockButtons.find(
      (button) => button.label === "Expand",
    ) as { onPress: () => void };
    mockButtons = [];
    await act(async () => {
      expandButton.onPress();
    });

    expect(mockButtons.some((button) => button.label === "Collapse")).toBe(
      true,
    );
    expect(
      mockButtons.some((button) => button.label === "Attention Agent"),
    ).toBe(false);
  });
});
