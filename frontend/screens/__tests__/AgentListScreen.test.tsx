import { Text } from "react-native";
import { act, create } from "react-test-renderer";

import { AgentListScreen } from "@/screens/AgentListScreen";

const mockPush = jest.fn();
const mockSetActiveAgent = jest.fn();
const mockInvalidateQueries = jest.fn(() => Promise.resolve());
const mockBatchMutate = jest.fn();
const mockBlurActiveElement = jest.fn();
const mockPersonalLoadMore = jest.fn(async () => {});
const mockSharedLoadMore = jest.fn(async () => {});
const mockPersonalRefresh = jest.fn(async () => {});
const mockSharedRefresh = jest.fn(async () => {});
const mockPersonalQueryCalls: {
  healthBucket: string;
  enabled?: boolean;
}[] = [];
const mockSharedQueryCalls: { enabled?: boolean }[] = [];

let mockButtons: Record<string, unknown>[] = [];

const mockPersonalCounts = {
  healthy: 1,
  degraded: 1,
  unavailable: 1,
  unknown: 1,
};

const buildPersonalAgent = (
  healthStatus: "healthy" | "degraded" | "unavailable" | "unknown",
) => ({
  id: `personal-${healthStatus}-1`,
  name: `${healthStatus[0].toUpperCase()}${healthStatus.slice(1)} Agent`,
  card_url: `https://example.com/${healthStatus}.json`,
  auth_type: "none",
  enabled: true,
  health_status: healthStatus,
  consecutive_health_check_failures: healthStatus === "healthy" ? 0 : 1,
  last_health_check_at: "2026-03-25T10:00:00.000Z",
  last_successful_health_check_at:
    healthStatus === "healthy" ? "2026-03-25T10:00:00.000Z" : null,
  last_health_check_error:
    healthStatus === "healthy" ? null : "Connection failed",
  tags: [],
  extra_headers: {},
  created_at: "2026-03-25T09:00:00.000Z",
  updated_at: "2026-03-25T09:00:00.000Z",
});

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

jest.mock("@/hooks/useAgentListQueries", () => ({
  usePersonalAgentsListQuery: ({
    healthBucket,
    enabled,
  }: {
    healthBucket: string;
    enabled?: boolean;
  }) => {
    mockPersonalQueryCalls.push({ healthBucket, enabled });

    return {
      items:
        healthBucket === "healthy" ||
        healthBucket === "degraded" ||
        healthBucket === "unavailable" ||
        healthBucket === "unknown"
          ? [buildPersonalAgent(healthBucket)]
          : [],
      counts: mockPersonalCounts,
      pages: [],
      error: null,
      isError: false,
      nextPage: 2,
      hasMore: true,
      loading: false,
      refreshing: false,
      loadingMore: false,
      setItems: jest.fn(),
      reset: jest.fn(),
      loadFirstPage: jest.fn(async () => true),
      refresh: mockPersonalRefresh,
      loadMore: mockPersonalLoadMore,
    };
  },
  useSharedAgentsListQuery: ({ enabled }: { enabled?: boolean }) => {
    mockSharedQueryCalls.push({ enabled });

    return {
      items: [
        {
          id: "shared-1",
          name: "Shared Agent 1",
          card_url: "https://example.com/shared-1.json",
          auth_type: "none",
          credential_mode: "shared",
          credential_configured: true,
          credential_display_hint: null,
          tags: [],
        },
      ],
      pages: [],
      error: null,
      isError: false,
      nextPage: 2,
      hasMore: true,
      loading: false,
      refreshing: false,
      loadingMore: false,
      setItems: jest.fn(),
      reset: jest.fn(),
      loadFirstPage: jest.fn(async () => true),
      refresh: mockSharedRefresh,
      loadMore: mockSharedLoadMore,
    };
  },
}));

jest.mock("@/lib/api/a2aAgents", () => ({
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
    mockPersonalQueryCalls.length = 0;
    mockSharedQueryCalls.length = 0;
    jest.clearAllMocks();
  });

  it("renders personal agents with continuous loading actions", async () => {
    let tree: ReturnType<typeof create>;

    await act(async () => {
      tree = create(<AgentListScreen />);
    });

    expect(mockButtons.some((button) => button.label === "My")).toBe(true);
    expect(mockButtons.some((button) => button.label === "Shared")).toBe(true);
    expect(mockButtons.some((button) => button.label === "Check")).toBe(true);
    expect(mockButtons.some((button) => button.label === "Load more")).toBe(
      true,
    );
    expect(mockButtons.some((button) => button.label === "Previous")).toBe(
      false,
    );
    expect(mockButtons.some((button) => button.label === "Next")).toBe(false);

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
      (button) => button.label === "Check",
    ) as { onPress: () => void };
    await act(async () => {
      batchButton.onPress();
    });

    expect(mockBatchMutate).toHaveBeenCalled();

    const loadMoreButton = mockButtons.find(
      (button) => button.label === "Load more",
    ) as { onPress: () => void };
    await act(async () => {
      await loadMoreButton.onPress();
    });

    expect(mockPersonalLoadMore).toHaveBeenCalled();

    const degradedFilterButton = mockButtons.find(
      (button) => button.label === "Degraded 1",
    ) as { onPress: () => void };
    mockButtons = [];
    await act(async () => {
      degradedFilterButton.onPress();
      tree!.update(<AgentListScreen />);
    });

    expect(mockPersonalQueryCalls[mockPersonalQueryCalls.length - 1]).toEqual({
      healthBucket: "degraded",
      enabled: true,
    });
  });

  it("shows shared cards and uses shared load more after switching tabs", async () => {
    let tree: ReturnType<typeof create>;

    await act(async () => {
      tree = create(<AgentListScreen />);
    });

    const sharedTabButton = mockButtons.find(
      (button) => button.label === "Shared",
    ) as { onPress: () => void };

    mockButtons = [];
    await act(async () => {
      sharedTabButton.onPress();
      tree!.update(<AgentListScreen />);
    });

    expect(mockButtons.some((button) => button.label === "Details")).toBe(true);
    expect(mockButtons.some((button) => button.label === "Check")).toBe(false);
    expect(mockButtons.some((button) => button.label === "Load more")).toBe(
      true,
    );
    expect(mockSharedQueryCalls[mockSharedQueryCalls.length - 1]).toEqual({
      enabled: true,
    });

    const loadMoreButton = mockButtons.find(
      (button) => button.label === "Load more",
    ) as { onPress: () => void };
    await act(async () => {
      await loadMoreButton.onPress();
    });

    expect(mockSharedLoadMore).toHaveBeenCalled();
  });

  it("keeps personal cards visually minimal by hiding personal markers", async () => {
    let tree: ReturnType<typeof create>;

    await act(async () => {
      tree = create(<AgentListScreen />);
    });

    const textContent = tree!.root
      .findAllByType(Text)
      .flatMap((node) => node.props.children)
      .join(" ");

    expect(textContent).not.toContain("PERSONAL");
    expect(textContent).not.toContain("Enabled");
    expect(textContent).not.toContain("Checked");
    expect(textContent).not.toContain("SHARED");
  });

  it("shows shared cards only after switching to the shared tab", async () => {
    let tree: ReturnType<typeof create>;

    await act(async () => {
      tree = create(<AgentListScreen />);
    });

    let textContent = tree!.root
      .findAllByType(Text)
      .flatMap((node) => node.props.children)
      .join(" ");

    expect(textContent).not.toContain("SHARED");

    const sharedTabButton = mockButtons.find(
      (button) => button.label === "Shared",
    ) as { onPress: () => void };

    mockButtons = [];
    await act(async () => {
      sharedTabButton.onPress();
      tree!.update(<AgentListScreen />);
    });

    textContent = tree!.root
      .findAllByType(Text)
      .flatMap((node) => node.props.children)
      .join(" ");

    expect(textContent).toContain("SHARED");
  });
});
