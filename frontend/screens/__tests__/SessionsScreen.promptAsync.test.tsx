import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { SessionsScreen } from "@/screens/SessionsScreen";

const mockContinueSession = jest.fn();
const mockLoadMore = jest.fn();

const sessionsItems = [
  {
    conversationId: "conv-opencode-1",
    source: "manual",
    external_provider: "opencode",
    external_session_id: "ses-op-1",
    agent_id: "agent-1",
    agent_source: "shared",
    title: "OpenCode Session",
    last_active_at: "2026-02-24T00:00:00Z",
    created_at: "2026-02-24T00:00:00Z",
  },
];

jest.mock("react-native/Libraries/Utilities/Dimensions", () => {
  const dimensions = {
    window: { width: 375, height: 812, scale: 2, fontScale: 2 },
    screen: { width: 375, height: 812, scale: 2, fontScale: 2 },
  };
  const dimensionsModule = {
    get: (key: "window" | "screen") => dimensions[key],
    set: jest.fn(),
    addEventListener: () => ({
      remove: jest.fn(),
    }),
    removeEventListener: jest.fn(),
  };
  return {
    __esModule: true,
    default: dimensionsModule,
    ...dimensionsModule,
  };
});

jest.mock("@/components/layout/ScreenContainer", () => ({
  ScreenContainer: ({ children }: { children: unknown }) => children,
}));

jest.mock("@/components/ui/PageHeader", () => ({
  PageHeader: () => null,
}));

jest.mock("@/hooks/useContinueSession", () => ({
  useContinueSession: () => ({
    continueSession: (...args: unknown[]) => mockContinueSession(...args),
  }),
}));

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: [
      {
        id: "agent-1",
        source: "shared",
        name: "Shared Agent",
      },
    ],
  }),
}));

jest.mock("@/hooks/useSessionsDirectoryQuery", () => ({
  useSessionsDirectoryQuery: () => ({
    items: sessionsItems,
    hasMore: false,
    loading: false,
    refreshing: false,
    loadingMore: false,
    refresh: jest.fn(),
    loadMore: (...args: unknown[]) => mockLoadMore(...args),
  }),
}));

describe("SessionsScreen Async Continue visibility", () => {
  beforeEach(() => {
    mockContinueSession.mockReset();
    mockLoadMore.mockReset();
  });

  it("does not render async continue entry in sessions cards", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<SessionsScreen />);
    });

    expect(tree.root.findAllByProps({ label: "Async Continue" })).toHaveLength(
      0,
    );
  });
});
