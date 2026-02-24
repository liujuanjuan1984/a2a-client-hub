import { FlatList } from "react-native";
import {
  act,
  create,
  type ReactTestInstance,
  type ReactTestRenderer,
} from "react-test-renderer";

import { ChatScreen } from "@/screens/ChatScreen";

const mockReplyPermission = jest.fn();
const mockReplyQuestion = jest.fn();
const mockRejectQuestion = jest.fn();
const mockToastInfo = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockContinueSession = jest.fn();
const mockSyncShortcuts = jest.fn();
const mockAddShortcut = jest.fn();
const mockUpdateShortcut = jest.fn();
const mockRemoveShortcut = jest.fn();
const mockAgentStoreState = {
  activeAgentId: "agent-1",
};

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

jest.mock("react-native/Libraries/Modal/Modal", () => {
  return {
    __esModule: true,
    default: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
    Modal: ({
      children,
      visible = false,
    }: {
      children?: unknown;
      visible?: boolean;
    }) => (visible ? children : null),
  };
});

jest.mock("@expo/vector-icons", () => ({
  Ionicons: () => null,
}));

type MockAgentSession = {
  agentId: string;
  source: "manual" | "scheduled" | null;
  contextId: string | null;
  runtimeStatus: string | null;
  pendingInterrupt: unknown;
  streamState: "idle" | "streaming" | "recoverable" | "error";
  lastStreamError: string | null;
  transport: string;
  inputModes: string[];
  outputModes: string[];
  metadata: Record<string, unknown>;
  externalSessionRef: {
    provider: string | null;
    externalSessionId: string | null;
  } | null;
  lastActiveAt: string;
};

const baseSession = (): MockAgentSession => ({
  agentId: "agent-1",
  source: "manual",
  contextId: "ctx-1",
  runtimeStatus: "input-required",
  pendingInterrupt: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "ws",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  externalSessionRef: null,
  lastActiveAt: "2026-02-16T00:00:00.000Z",
});

const mockChatState: {
  sessions: Record<string, MockAgentSession>;
  ensureSession: jest.Mock;
  generateConversationId: jest.Mock;
  sendMessage: jest.Mock;
  clearPendingInterrupt: jest.Mock;
  bindExternalSession: jest.Mock;
  getSessionsByAgentId: jest.Mock;
} = {
  sessions: {},
  ensureSession: jest.fn(),
  generateConversationId: jest.fn(() => "conversation-next"),
  sendMessage: jest.fn(),
  clearPendingInterrupt: jest.fn(),
  bindExternalSession: jest.fn(),
  getSessionsByAgentId: jest.fn(() => []),
};

const mockMessageState: {
  messages: Record<
    string,
    { id: string; role: string; content: string; createdAt: string }[]
  >;
  setMessages: jest.Mock;
} = {
  messages: {},
  setMessages: jest.fn(),
};

type MockShortcut = {
  id: string;
  title: string;
  prompt: string;
  isDefault: boolean;
  order: number;
};

const mockShortcutState: {
  shortcuts: MockShortcut[];
  isSyncing: boolean;
  syncError: string | null;
  syncShortcuts: jest.Mock;
  addShortcut: jest.Mock;
  updateShortcut: jest.Mock;
  removeShortcut: jest.Mock;
  getShortcutsForAgent: jest.Mock;
} = {
  shortcuts: [],
  isSyncing: false,
  syncError: null,
  syncShortcuts: mockSyncShortcuts,
  addShortcut: mockAddShortcut,
  updateShortcut: mockUpdateShortcut,
  removeShortcut: mockRemoveShortcut,
  getShortcutsForAgent: jest
    .fn()
    .mockImplementation(() => mockShortcutState.shortcuts),
};

const mockSessionHistoryState = {
  loading: false,
  loadingMore: false,
  nextPage: undefined as number | undefined,
  error: null as Error | null,
  messages: [] as unknown[],
  loadMore: jest.fn(),
};

const mockUseChatStore = ((
  selector: (state: typeof mockChatState) => unknown,
) => selector(mockChatState)) as unknown as {
  (selector: (state: typeof mockChatState) => unknown): unknown;
  getState: () => typeof mockChatState;
};
mockUseChatStore.getState = () => mockChatState;

const mockUseMessageStore = ((
  selector: (state: typeof mockMessageState) => unknown,
) => selector(mockMessageState)) as unknown as {
  (selector: (state: typeof mockMessageState) => unknown): unknown;
  getState: () => typeof mockMessageState;
};
mockUseMessageStore.getState = () => mockMessageState;

jest.mock("expo-router", () => ({
  useRouter: () => ({
    replace: jest.fn(),
    back: jest.fn(),
  }),
  useFocusEffect: jest.fn(),
}));

jest.mock("@/components/layout/useAppSafeArea", () => ({
  useAppSafeArea: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

jest.mock("@/hooks/useAgentsCatalogQuery", () => ({
  useAgentsCatalogQuery: () => ({
    data: [
      {
        id: "agent-1",
        source: "personal",
        name: "Agent One",
        cardUrl: "https://example.com/a2a",
        status: "success",
      },
    ],
    isFetched: true,
  }),
  useValidateAgentMutation: () => ({
    mutateAsync: jest.fn(),
    isPending: false,
  }),
}));

jest.mock("@/hooks/useChatHistoryQuery", () => ({
  useSessionHistoryQuery: () => mockSessionHistoryState,
}));

jest.mock("@/store/chat", () => ({
  useChatStore: (selector: (state: typeof mockChatState) => unknown) =>
    mockUseChatStore(selector),
}));

jest.mock("@/store/agents", () => ({
  useAgentStore: (selector: (state: typeof mockAgentStoreState) => unknown) =>
    selector(mockAgentStoreState),
}));

jest.mock("@/store/messages", () => ({
  useMessageStore: (selector: (state: typeof mockMessageState) => unknown) =>
    mockUseMessageStore(selector),
}));

jest.mock("@/store/shortcuts", () => ({
  useShortcutStore: () => mockShortcutState,
}));

jest.mock("@/lib/api/sessions", () => ({
  continueSession: (...args: unknown[]) => mockContinueSession(...args),
}));

jest.mock("@/lib/api/a2aExtensions", () => ({
  A2AExtensionCallError: class extends Error {
    errorCode: string | null = null;
    upstreamError: Record<string, unknown> | null = null;
  },
  replyOpencodePermissionInterrupt: (...args: unknown[]) =>
    mockReplyPermission(...args),
  replyOpencodeQuestionInterrupt: (...args: unknown[]) =>
    mockReplyQuestion(...args),
  rejectOpencodeQuestionInterrupt: (...args: unknown[]) =>
    mockRejectQuestion(...args),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    info: (...args: unknown[]) => mockToastInfo(...args),
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

const containsText = (node: ReactTestInstance, text: string): boolean => {
  const children = node.props.children;
  if (typeof children === "string" && children.includes(text)) {
    return true;
  }
  if (Array.isArray(children)) {
    for (const child of children) {
      if (typeof child === "string" && child.includes(text)) {
        return true;
      }
    }
  }
  for (const child of node.children) {
    if (typeof child === "object" && child && containsText(child, text)) {
      return true;
    }
  }
  return false;
};

const renderChatScreen = (conversationId: string) => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ChatScreen agentId="agent-1" conversationId={conversationId} />,
    );
  });
  return tree;
};

describe("ChatScreen interrupt handling", () => {
  const conversationId = "conversation-1";

  beforeEach(() => {
    mockSyncShortcuts.mockReset().mockResolvedValue(undefined);
    mockAddShortcut.mockReset().mockResolvedValue(undefined);
    mockUpdateShortcut.mockReset().mockResolvedValue(undefined);
    mockRemoveShortcut.mockReset().mockResolvedValue(undefined);
    mockReplyPermission.mockReset();
    mockReplyQuestion.mockReset();
    mockRejectQuestion.mockReset();
    mockToastInfo.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockContinueSession.mockReset();
    mockChatState.ensureSession.mockReset();
    mockChatState.generateConversationId
      .mockReset()
      .mockReturnValue("conversation-next");
    mockChatState.sendMessage.mockReset();
    mockChatState.clearPendingInterrupt.mockReset();
    mockChatState.bindExternalSession.mockReset();
    mockMessageState.setMessages.mockReset();
    mockMessageState.messages = { [conversationId]: [] };
    mockSessionHistoryState.loadMore.mockReset();
    mockSessionHistoryState.messages = [];
    mockSessionHistoryState.error = null;
    mockSessionHistoryState.loading = false;
    mockSessionHistoryState.loadingMore = false;
    mockSessionHistoryState.nextPage = undefined;
    mockShortcutState.shortcuts = [];
    mockContinueSession.mockResolvedValue({});
    mockReplyPermission.mockResolvedValue({ ok: true, requestId: "perm-1" });
    mockReplyQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
    mockRejectQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
    mockChatState.sessions = {
      [conversationId]: baseSession(),
    };
    global.requestAnimationFrame = ((callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    }) as unknown as (callback: FrameRequestCallback) => number;
  });

  it("disables sending and shows prompt when pending permission interrupt exists", () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-1",
        type: "permission",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
        },
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    act(() => {
      input.props.onChangeText("hello");
    });

    const sendButton = root.findByProps({ testID: "chat-send-button" });
    expect(sendButton.props.disabled).toBe(true);
    expect(
      containsText(
        root,
        "Agent is waiting for authorization/input. Resolve the action card first.",
      ),
    ).toBe(true);
    act(() => {
      tree.unmount();
    });
  });

  it("submits permission reply through extension callback and clears pending interrupt", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-1",
        type: "permission",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
        },
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const allowOnceButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      allowOnceButton.props.onPress();
    });

    expect(mockReplyPermission).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "perm-1",
      reply: "once",
    });
    expect(mockChatState.clearPendingInterrupt).toHaveBeenCalledWith(
      conversationId,
      "perm-1",
    );
    expect(mockToastSuccess).toHaveBeenCalled();
    act(() => {
      tree.unmount();
    });
  });

  it("submits question answers through extension callback and clears pending interrupt", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "q-1",
        type: "question",
        details: {
          questions: [
            {
              header: "Confirm",
              question: "Proceed?",
              options: [],
            },
          ],
        },
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const answerInput = root.findByProps({
      testID: "interrupt-question-input-0",
    });
    const submitButton = root.findByProps({
      testID: "interrupt-question-submit",
    });

    act(() => {
      answerInput.props.onChangeText("yes");
    });
    await act(async () => {
      submitButton.props.onPress();
    });

    expect(mockReplyQuestion).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      requestId: "q-1",
      answers: [["yes"]],
    });
    expect(mockChatState.clearPendingInterrupt).toHaveBeenCalledWith(
      conversationId,
      "q-1",
    );
    expect(mockToastSuccess).toHaveBeenCalled();
    act(() => {
      tree.unmount();
    });
  });

  it("uses explicit expand/collapse for long plain text messages", async () => {
    mockMessageState.messages = {
      [conversationId]: [
        {
          id: "message-1",
          role: "agent",
          content: "A".repeat(5000),
          createdAt: "2026-02-16T00:00:00.000Z",
        },
      ],
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const expandButton = root.findAll((node) => {
      return (
        node.type === Object({}) ||
        node.props?.testID === "chat-message-message-1-expand"
      );
    })[0];

    expect(expandButton).toBeDefined();
    expect(expandButton?.props.accessibilityLabel).toBe("Expand full text");

    act(() => {
      expandButton.props.onPress();
    });

    const collapseButton = root.findByProps({
      testID: "chat-message-message-1-expand",
      accessibilityLabel: "Collapse full text",
    });
    expect(collapseButton).toBeDefined();
    const bottomCollapseButton = root.findByProps({
      testID: "chat-message-message-1-collapse-bottom",
      accessibilityLabel: "Collapse full text",
    });
    expect(bottomCollapseButton).toBeDefined();
    act(() => {
      tree.unmount();
    });
  });

  it("keeps viewport anchored when content grows after expanding a block", () => {
    const flatListProto = FlatList.prototype as {
      scrollToOffset?: (params: { offset: number; animated: boolean }) => void;
    };
    const originalScrollToOffset = flatListProto.scrollToOffset;
    const scrollToOffsetSpy = jest.fn();
    flatListProto.scrollToOffset = scrollToOffsetSpy;

    try {
      mockMessageState.messages = {
        [conversationId]: [
          {
            id: "message-anchor",
            role: "agent",
            content: "A".repeat(5000),
            createdAt: "2026-02-16T00:00:00.000Z",
          },
        ],
      };

      const tree = renderChatScreen(conversationId);
      const root = tree.root;
      const list = root.findByType(FlatList);

      act(() => {
        list.props.onScroll({
          nativeEvent: {
            contentOffset: { y: 120 },
            layoutMeasurement: { height: 600 },
            contentSize: { height: 1000 },
          },
        });
        list.props.onContentSizeChange(0, 1000);
      });

      act(() => {
        root
          .findByProps({ testID: "chat-message-message-anchor-expand" })
          .props.onPress();
      });

      act(() => {
        list.props.onContentSizeChange(0, 1120);
      });

      expect(scrollToOffsetSpy).toHaveBeenCalledWith({
        offset: 240,
        animated: false,
      });

      act(() => {
        tree.unmount();
      });
    } finally {
      flatListProto.scrollToOffset = originalScrollToOffset;
    }
  });

  it("creates shortcut through modal with separate title and prompt", async () => {
    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const toggleShortcutButton = root.findByProps({
      accessibilityLabel: "Open shortcut manager",
    });

    act(() => {
      toggleShortcutButton.props.onPress();
    });

    const createShortcutButton = root.findByProps({ label: "New Shortcut" });
    await act(async () => {
      await createShortcutButton.props.onPress();
    });

    const titleInput = root.findByProps({ placeholder: "Shortcut title" });
    const promptInput = root.findByProps({ placeholder: "Prompt" });
    act(() => {
      titleInput.props.onChangeText("Daily Summary");
      promptInput.props.onChangeText("Summarize today in 3 points.");
    });

    const saveButton = root.findByProps({ label: "Save" });
    await act(async () => {
      await saveButton.props.onPress();
    });

    expect(mockAddShortcut).toHaveBeenCalledWith(
      "Daily Summary",
      "Summarize today in 3 points.",
      null,
    );
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Shortcut saved",
      '"Daily Summary" is now available.',
    );
    act(() => {
      tree.unmount();
    });
  });

  it("edits existing shortcut and updates title/prompt", async () => {
    mockShortcutState.shortcuts = [
      {
        id: "shortcut-1",
        title: "Old title",
        prompt: "Old prompt",
        isDefault: false,
        order: 0,
      },
    ];

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const toggleShortcutButton = root.findByProps({
      accessibilityLabel: "Open shortcut manager",
    });

    act(() => {
      toggleShortcutButton.props.onPress();
    });

    const editShortcutButton = root.findByProps({
      accessibilityLabel: "Edit shortcut Old title",
    });
    await act(async () => {
      await editShortcutButton.props.onPress();
    });

    const titleInput = root.findByProps({ placeholder: "Shortcut title" });
    const promptInput = root.findByProps({ placeholder: "Prompt" });
    act(() => {
      titleInput.props.onChangeText("Updated title");
      promptInput.props.onChangeText("Updated prompt");
    });

    const updateButton = root.findByProps({ label: "Update" });
    await act(async () => {
      await updateButton.props.onPress();
    });

    expect(mockUpdateShortcut).toHaveBeenCalledWith(
      "shortcut-1",
      "Updated title",
      "Updated prompt",
      "agent-1",
      false,
    );
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Shortcut updated",
      '"Updated title" has been updated.',
    );
    act(() => {
      tree.unmount();
    });
  });

  it("does not show edit action for default shortcut", () => {
    mockShortcutState.shortcuts = [
      {
        id: "shortcut-default",
        title: "Default title",
        prompt: "Default prompt",
        isDefault: true,
        order: 0,
      },
    ];

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const toggleShortcutButton = root.findByProps({
      accessibilityLabel: "Open shortcut manager",
    });

    act(() => {
      toggleShortcutButton.props.onPress();
    });

    const editActions = root.findAll((node) => {
      return (
        typeof node.props.accessibilityLabel === "string" &&
        node.props.accessibilityLabel.startsWith("Edit shortcut")
      );
    });

    expect(editActions).toHaveLength(0);
    act(() => {
      tree.unmount();
    });
  });
});
