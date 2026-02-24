import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { SessionsScreen } from "@/screens/SessionsScreen";

const mockContinueSession = jest.fn();
const mockPromptOpencodeSessionAsync = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockRefresh = jest.fn();
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
    refresh: (...args: unknown[]) => mockRefresh(...args),
    loadMore: (...args: unknown[]) => mockLoadMore(...args),
  }),
}));

jest.mock("@/lib/api/a2aExtensions", () => ({
  A2AExtensionCallError: class extends Error {
    errorCode: string | null = null;
    upstreamError: Record<string, unknown> | null = null;
  },
  promptOpencodeSessionAsync: (...args: unknown[]) =>
    mockPromptOpencodeSessionAsync(...args),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

describe("SessionsScreen prompt_async trigger", () => {
  beforeEach(() => {
    mockContinueSession.mockReset();
    mockPromptOpencodeSessionAsync.mockReset().mockResolvedValue({
      ok: true,
      sessionId: "ses-op-1",
    });
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockRefresh.mockReset().mockResolvedValue(undefined);
    mockLoadMore.mockReset();
  });

  it("triggers opencode prompt_async from sessions list", async () => {
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = create(<SessionsScreen />);
    });

    const asyncButton = tree.root.findByProps({ label: "Async Continue" });
    await act(async () => {
      await asyncButton.props.onPress();
    });

    expect(mockPromptOpencodeSessionAsync).toHaveBeenCalledWith({
      source: "shared",
      agentId: "agent-1",
      sessionId: "ses-op-1",
      request: {
        parts: [
          {
            type: "text",
            text: "Continue from the latest context and summarize next steps.",
          },
        ],
        noReply: true,
      },
    });
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Async continue started",
      "The upstream session accepted prompt_async.",
    );
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });
});
