import type { ReactNode } from "react";
import { Text } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

import { DEFAULT_API_KEY_HEADER } from "@/lib/agentHeaders";
import { AgentListScreen } from "@/screens/AgentListScreen";

const mockPush = jest.fn();
const mockSetActiveAgent = jest.fn();
const mockBlurActiveElement = jest.fn();
const mockBatchMutate = jest.fn();
const mockRefetchQueries = jest.fn(() => Promise.resolve());
const mockInvalidateQueries = jest.fn(() => Promise.resolve());

let mockButtons: Record<string, unknown>[] = [];
let mockFlatLists: Record<string, unknown>[] = [];
let mockAgents = [
  {
    id: "personal-1",
    source: "personal" as const,
    name: "Personal Agent",
    cardUrl: "https://example.com/personal.json",
    authType: "none" as const,
    bearerToken: "",
    apiKeyHeader: DEFAULT_API_KEY_HEADER,
    apiKeyValue: "",
    basicUsername: "",
    basicPassword: "",
    extraHeaders: [],
    invokeMetadataDefaults: [],
    status: "idle" as const,
    enabled: true,
    healthStatus: "healthy" as const,
    lastHealthCheckAt: "2026-04-13T12:00:00.000Z",
  },
  {
    id: "self-management-assistant",
    source: "builtin" as const,
    name: "A2A Client Hub Assistant",
    cardUrl: "builtin://self-management-assistant",
    authType: "none" as const,
    bearerToken: "",
    apiKeyHeader: DEFAULT_API_KEY_HEADER,
    apiKeyValue: "",
    basicUsername: "",
    basicPassword: "",
    extraHeaders: [],
    invokeMetadataDefaults: [],
    status: "idle" as const,
    enabled: true,
    healthStatus: "healthy" as const,
    description: "Built-in self-management assistant",
    resources: ["agents", "sessions"],
  },
  {
    id: "shared-1",
    source: "shared" as const,
    name: "Shared Agent",
    cardUrl: "https://example.com/shared.json",
    authType: "bearer" as const,
    bearerToken: "",
    apiKeyHeader: DEFAULT_API_KEY_HEADER,
    apiKeyValue: "",
    basicUsername: "",
    basicPassword: "",
    extraHeaders: [],
    invokeMetadataDefaults: [],
    status: "idle" as const,
    enabled: true,
    healthStatus: "unknown" as const,
    credentialMode: "user" as const,
    credentialConfigured: false,
  },
];

jest.mock("@tanstack/react-query", () => ({
  useMutation: () => ({
    isPending: false,
    mutate: mockBatchMutate,
  }),
  useQueryClient: () => ({
    refetchQueries: mockRefetchQueries,
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
    ...props
  }: any) => {
    mockFlatLists.push({ data, renderItem, ListHeaderComponent, ...props });
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
    return React.createElement(React.Fragment, null, ...children);
  };

  const RefreshControl = () => null;

  return new Proxy(actual, {
    get(target, prop, receiver) {
      if (prop === "FlatList") {
        return FlatList;
      }
      if (prop === "RefreshControl") {
        return RefreshControl;
      }
      return Reflect.get(target, prop, receiver);
    },
  });
});

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: mockAgents,
    isLoading: false,
    isRefetching: false,
    refetch: jest.fn(async () => undefined),
    error: null,
  }),
}));

jest.mock("@/lib/api/agentsCatalog", () => ({
  checkAgentsCatalogHealth: jest.fn(),
}));

jest.mock("@/lib/focus", () => ({
  blurActiveElement: () => mockBlurActiveElement(),
}));

jest.mock("@/components/ui/Button", () => ({
  Button: (props: Record<string, unknown>) => {
    const { Text: MockText } = jest.requireActual("react-native");
    mockButtons.push(props);
    return <MockText>{String(props.label ?? "")}</MockText>;
  },
}));

jest.mock("@/components/ui/IconButton", () => ({
  IconButton: () => null,
}));

jest.mock("@/components/layout/ScreenContainer", () => ({
  ScreenContainer: ({ children }: { children: ReactNode }) => children,
}));

jest.mock("@/store/agents", () => ({
  useAgentStore: (
    selector: (state: { setActiveAgent: typeof mockSetActiveAgent }) => unknown,
  ) => selector({ setActiveAgent: mockSetActiveAgent }),
}));

jest.mock("@/store/chat", () => ({
  useChatStore: {
    getState: () => ({
      getLatestConversationIdByAgentId: () => undefined,
      generateConversationId: () => "conv-1",
    }),
  },
}));

jest.mock("@/store/session", () => ({
  useSessionStore: (
    selector: (state: { user: { is_superuser: boolean } }) => unknown,
  ) => selector({ user: { is_superuser: false } }),
}));

describe("AgentListScreen", () => {
  beforeEach(() => {
    mockButtons = [];
    mockFlatLists = [];
    mockAgents = [...mockAgents];
    jest.clearAllMocks();
  });

  it("renders personal, shared, and built-in agents in one list", async () => {
    let tree;
    await act(async () => {
      tree = create(<AgentListScreen />);
    });

    expect(mockFlatLists).toHaveLength(1);
    const labels = mockButtons.map((button) => button.label);
    expect(labels).toContain("Check all");
    expect(labels).toContain("Edit");
    expect(labels).toContain("Details");
    expect(labels.filter((label) => label === "Chat")).toHaveLength(3);
    expect(labels).not.toContain("My");
    expect(labels).not.toContain("Shared");
    expect(
      tree!.root
        .findAllByType(Text)
        .some((node: ReactTestInstance) => node.props.children === "BUILT-IN"),
    ).toBe(true);
  });

  it("triggers a unified health check from the header action", async () => {
    await act(async () => {
      create(<AgentListScreen />);
    });

    const checkButton = mockButtons.find(
      (button) => button.label === "Check all",
    );
    expect(checkButton).toBeDefined();

    await act(async () => {
      (checkButton?.onPress as (() => void) | undefined)?.();
    });

    expect(mockBatchMutate).toHaveBeenCalledTimes(1);
  });

  it("opens chat for the built-in agent from the unified list", async () => {
    await act(async () => {
      create(<AgentListScreen />);
    });

    const chatButtons = mockButtons.filter(
      (button) =>
        button.label === "Chat" &&
        button.accessibilityHint === "Open chat with A2A Client Hub Assistant",
    );

    await act(async () => {
      (chatButtons[0]?.onPress as (() => void) | undefined)?.();
    });

    expect(mockSetActiveAgent).toHaveBeenCalledWith(
      "self-management-assistant",
    );
    expect(mockPush).toHaveBeenCalled();
  });
});
