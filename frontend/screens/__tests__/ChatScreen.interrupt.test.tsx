import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ApiRequestError } from "@/lib/api/client";
import { ChatScreen } from "@/screens/ChatScreen";

const SELF_MANAGEMENT_AGENT_ID = "self-management-assistant";

const mockReplyPermission = jest.fn();
const mockReplyPermissions = jest.fn();
const mockReplyQuestion = jest.fn();
const mockRejectQuestion = jest.fn();
const mockReplyElicitation = jest.fn();
const mockAppendSessionMessage = jest.fn();
const mockListSessionMessagesPage = jest.fn();
const mockRunSessionCommand = jest.fn();
const mockRecoverInterrupts = jest.fn();
const mockInvokeAgent = jest.fn();
const mockInvokeHubAgent = jest.fn();
const mockGetSelfManagementBuiltInAgentProfile = jest.fn();
const mockRunSelfManagementBuiltInAgent = jest.fn();
const mockRecoverSelfManagementBuiltInAgentInterrupts = jest.fn();
const mockReplySelfManagementBuiltInAgentPermissionInterrupt = jest.fn();
const mockAddConversationMessage = jest.fn();
const mockMergeConversationMessages = jest.fn();
const mockRemoveConversationMessage = jest.fn();
const mockSetConversationMessages = jest.fn();
const mockUpdateConversationMessage = jest.fn();
const mockToastInfo = jest.fn();
const mockToastSuccess = jest.fn();
const mockToastError = jest.fn();
const mockContinueSession = jest.fn();
const mockAddShortcut = jest.fn();
const mockUpdateShortcut = jest.fn();
const mockRemoveShortcut = jest.fn();
const mockAgentStoreState = {
  activeAgentId: "agent-1",
};
type MockCapabilityStatus = "supported" | "unsupported" | "unknown";

const mockExtensionCapabilitiesState = {
  modelSelectionStatus: "supported" as MockCapabilityStatus,
  providerDiscoveryStatus: "supported" as MockCapabilityStatus,
  interruptRecoveryStatus: "supported" as MockCapabilityStatus,
  sessionPromptAsyncStatus: "supported" as MockCapabilityStatus,
  sessionCommandStatus: "supported" as MockCapabilityStatus,
  sessionAppendStatus: "supported" as MockCapabilityStatus,
  sessionAppend: {
    declared: true,
    consumedByHub: true,
    status: "supported" as const,
    routeMode: "prompt_async" as const,
    requiresStreamIdentity: false,
  } as {
    declared: boolean;
    consumedByHub: boolean;
    status: "supported" | "unsupported";
    routeMode: "unsupported" | "prompt_async" | "turn_steer" | "hybrid";
    requiresStreamIdentity: boolean;
  } | null,
  invokeMetadataStatus: "unsupported" as MockCapabilityStatus,
  invokeMetadata: null as {
    fields: { name: string; required: boolean; description?: string | null }[];
  } | null,
  canShowModelPicker: true,
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

jest.mock("@expo/vector-icons/Ionicons", () => () => null);

jest.mock("@/components/chat/ChatHeaderPanel", () => ({
  ChatHeaderPanel: () => null,
}));

jest.mock("@/components/chat/SessionPickerModal", () => ({
  SessionPickerModal: () => null,
}));

jest.mock("@/components/chat/WorkingDirectoryModal", () => ({
  WorkingDirectoryModal: () => null,
}));

jest.mock("@/components/chat/InvokeMetadataModal", () => ({
  InvokeMetadataModal: () => null,
}));

jest.mock("@/components/chat/ShortcutManagerModal", () => ({
  ShortcutManagerModal: () => null,
}));

jest.mock("@/components/chat/ChatTimelinePanel", () => ({
  ChatTimelinePanel: (props: {
    messages?: { id: string; content: string }[];
    session?: { streamState?: string | null };
    pendingInterrupt?: {
      type?: string;
      details?: { questions?: { question?: string }[] };
    } | null;
    onInterruptStream?: () => void;
    onPermissionReply?: (
      reply: "once" | "always" | "reject",
    ) => void | Promise<void>;
    onQuestionAnswerChange?: (index: number, value: string) => void;
    onQuestionReply?: () => void | Promise<void>;
  }) => {
    const React = require("react");
    const { Pressable, Text, TextInput, View } = require("react-native");
    const [answer, setAnswer] = React.useState("");

    return (
      <View>
        {(props.messages ?? []).map((message) => (
          <Text key={message.id}>{message.content}</Text>
        ))}
        {props.session?.streamState === "streaming" ? (
          <Pressable
            testID="chat-interrupt-button"
            onPress={() => props.onInterruptStream?.()}
          >
            <Text>Interrupt</Text>
          </Pressable>
        ) : null}
        {!props.pendingInterrupt ? null : (
          <>
            <Text>
              Agent is waiting for authorization/input. Resolve the action card
              first.
            </Text>
            {props.pendingInterrupt.type === "permission" ? (
              <>
                <Pressable
                  testID="interrupt-permission-once"
                  onPress={() => props.onPermissionReply?.("once")}
                >
                  <Text>Allow once</Text>
                </Pressable>
                <Pressable
                  testID="interrupt-permission-always"
                  onPress={() => props.onPermissionReply?.("always")}
                >
                  <Text>Always allow</Text>
                </Pressable>
                <Pressable
                  testID="interrupt-permission-reject"
                  onPress={() => props.onPermissionReply?.("reject")}
                >
                  <Text>Reject</Text>
                </Pressable>
              </>
            ) : null}
            {props.pendingInterrupt.type === "question" ? (
              <>
                <TextInput
                  testID="interrupt-question-input-0"
                  value={answer}
                  onChangeText={(value: string) => {
                    setAnswer(value);
                    props.onQuestionAnswerChange?.(0, value);
                  }}
                />
                <Pressable
                  testID="interrupt-question-submit"
                  onPress={() => props.onQuestionReply?.()}
                >
                  <Text>Submit</Text>
                </Pressable>
              </>
            ) : null}
          </>
        )}
      </View>
    );
  },
}));

jest.mock("@/components/chat/ChatComposer", () => ({
  ChatComposer: (props: {
    input?: string;
    pendingInterrupt?: unknown;
    onInputChange?: (value: string) => void;
    onSubmit?: () => void;
  }) => {
    const { Pressable, TextInput, View } = require("react-native");
    const disabled = Boolean(props.pendingInterrupt);
    return (
      <View>
        <TextInput
          placeholder="Type your message"
          value={props.input ?? ""}
          onChangeText={props.onInputChange}
        />
        <Pressable
          testID="chat-send-button"
          disabled={disabled}
          onPress={props.onSubmit}
        />
      </View>
    );
  },
}));

type MockAgentSession = {
  agentId: string;
  source: "manual" | "scheduled" | null;
  runtimeStatus: string | null;
  pendingInterrupts: unknown[];
  pendingInterrupt: unknown;
  lastResolvedInterrupt: unknown;
  streamState: "idle" | "streaming" | "continuing" | "recoverable" | "error";
  lastStreamError: string | null;
  transport: string;
  inputModes: string[];
  outputModes: string[];
  metadata: Record<string, unknown>;
  workingDirectory?: string | null;
  externalSessionRef: {
    provider: string | null;
    externalSessionId: string | null;
  } | null;
  lastActiveAt: string;
};

const baseSession = (): MockAgentSession => ({
  agentId: "agent-1",
  source: "manual",
  runtimeStatus: "input-required",
  pendingInterrupts: [],
  pendingInterrupt: null,
  lastResolvedInterrupt: null,
  streamState: "idle",
  lastStreamError: null,
  transport: "ws",
  inputModes: ["text/plain"],
  outputModes: ["text/plain"],
  metadata: {},
  workingDirectory: null,
  externalSessionRef: null,
  lastActiveAt: "2026-02-16T00:00:00.000Z",
});

const mockChatState: {
  sessions: Record<string, MockAgentSession>;
  ensureSession: jest.Mock;
  generateConversationId: jest.Mock;
  sendMessage: jest.Mock;
  cancelMessage: jest.Mock;
  clearPendingInterrupt: jest.Mock;
  replaceRecoveredInterrupts: jest.Mock;
  bindExternalSession: jest.Mock;
  setWorkingDirectory: jest.Mock;
  setInvokeMetadataBindings: jest.Mock;
  getSessionsByAgentId: jest.Mock;
  setState?: (
    updater:
      | typeof mockChatState
      | ((state: typeof mockChatState) => Partial<typeof mockChatState>),
  ) => void;
} = {
  sessions: {},
  ensureSession: jest.fn(),
  generateConversationId: jest.fn(() => "conversation-next"),
  sendMessage: jest.fn(),
  cancelMessage: jest.fn(),
  clearPendingInterrupt: jest.fn(),
  replaceRecoveredInterrupts: jest.fn(),
  bindExternalSession: jest.fn(),
  setWorkingDirectory: jest.fn(),
  setInvokeMetadataBindings: jest.fn(),
  getSessionsByAgentId: jest.fn(() => []),
};

mockChatState.setState = (updater) => {
  const nextState =
    typeof updater === "function" ? updater(mockChatState) : updater;
  Object.assign(mockChatState, nextState);
};

type MockShortcut = {
  id: string;
  title: string;
  prompt: string;
  isDefault: boolean;
  order: number;
  agentId?: string | null;
};

const mockShortcutQueryState: {
  shortcuts: MockShortcut[];
  getShortcutsForAgent: jest.Mock;
} = {
  shortcuts: [],
  getShortcutsForAgent: jest
    .fn()
    .mockImplementation(() => mockShortcutQueryState.shortcuts),
};

const mockSessionHistoryState = {
  loading: false,
  loadingMore: false,
  nextPage: undefined as number | undefined,
  error: null as Error | null,
  messages: [] as unknown[],
  loadMore: jest.fn(),
  loadMessageBlocks: jest.fn(async () => {}),
  isMessageBlocksLoading: jest.fn(() => false),
};

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
      {
        id: SELF_MANAGEMENT_AGENT_ID,
        source: "builtin",
        name: "A2A Client Hub Assistant",
        cardUrl: "builtin://self-management-assistant",
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

jest.mock("@/hooks/useExtensionCapabilitiesQuery", () => ({
  useExtensionCapabilitiesQuery: () => mockExtensionCapabilitiesState,
}));

jest.mock("@/hooks/useSessionsDirectoryQuery", () => ({
  useSessionsDirectoryQuery: () => ({
    error: null,
    isError: false,
    items: [],
    setItems: jest.fn(),
    nextPage: null,
    hasMore: false,
    loading: false,
    refreshing: false,
    loadingMore: false,
    reset: jest.fn(),
    loadFirstPage: jest.fn(async () => true),
    loadMore: jest.fn(async () => {}),
    refresh: jest.fn(async () => {}),
  }),
}));

jest.mock("@/store/chat", () => {
  const useChatStore = Object.assign(
    (selector: (state: typeof mockChatState) => unknown) =>
      selector(mockChatState),
    {
      getState: () => mockChatState,
      setState: (
        updater: Parameters<NonNullable<typeof mockChatState.setState>>[0],
      ) => mockChatState.setState?.(updater),
    },
  );
  return { useChatStore };
});

jest.mock("@/store/agents", () => ({
  useAgentStore: (selector: (state: typeof mockAgentStoreState) => unknown) =>
    selector(mockAgentStoreState),
}));

jest.mock("@/hooks/useShortcutsQuery", () => ({
  useShortcutsQuery: () => mockShortcutQueryState,
  useCreateShortcutMutation: () => ({
    mutateAsync: (...args: unknown[]) => mockAddShortcut(...args),
  }),
  useUpdateShortcutMutation: () => ({
    mutateAsync: (...args: unknown[]) => mockUpdateShortcut(...args),
  }),
  useDeleteShortcutMutation: () => ({
    mutateAsync: (...args: unknown[]) => mockRemoveShortcut(...args),
  }),
}));

jest.mock("@/lib/api/sessions", () => ({
  appendSessionMessage: (...args: unknown[]) =>
    mockAppendSessionMessage(...args),
  continueSession: (...args: unknown[]) => mockContinueSession(...args),
  listSessionMessagesPage: (...args: unknown[]) =>
    mockListSessionMessagesPage(...args),
  querySessionMessageBlocks: jest.fn(async () => ({ items: [] })),
  runSessionCommand: (...args: unknown[]) => mockRunSessionCommand(...args),
}));

jest.mock("@/lib/api/a2aExtensions", () => ({
  A2AExtensionCallError: class extends Error {
    errorCode: string | null = null;
    upstreamError: Record<string, unknown> | null = null;
  },
  recoverInterrupts: (...args: unknown[]) => mockRecoverInterrupts(...args),
  replyPermissionInterrupt: (...args: unknown[]) =>
    mockReplyPermission(...args),
  replyPermissionsInterrupt: (...args: unknown[]) =>
    mockReplyPermissions(...args),
  replyQuestionInterrupt: (...args: unknown[]) => mockReplyQuestion(...args),
  rejectQuestionInterrupt: (...args: unknown[]) => mockRejectQuestion(...args),
  replyElicitationInterrupt: (...args: unknown[]) =>
    mockReplyElicitation(...args),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  invokeAgent: (...args: unknown[]) => mockInvokeAgent(...args),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  invokeHubAgent: (...args: unknown[]) => mockInvokeHubAgent(...args),
}));

jest.mock("@/lib/chatHistoryCache", () => ({
  addConversationMessage: (...args: unknown[]) =>
    mockAddConversationMessage(...args),
  mergeConversationMessages: (...args: unknown[]) =>
    mockMergeConversationMessages(...args),
  removeConversationMessage: (...args: unknown[]) =>
    mockRemoveConversationMessage(...args),
  setConversationMessages: (...args: unknown[]) =>
    mockSetConversationMessages(...args),
  updateConversationMessage: (...args: unknown[]) =>
    mockUpdateConversationMessage(...args),
}));

jest.mock("@/lib/api/selfManagementAgent", () => ({
  SELF_MANAGEMENT_BUILT_IN_AGENT_ID: SELF_MANAGEMENT_AGENT_ID,
  isSelfManagementBuiltInAgent: (agentId?: string | null) =>
    (agentId ?? "").trim() === SELF_MANAGEMENT_AGENT_ID,
  getSelfManagementBuiltInAgentProfile: (...args: unknown[]) =>
    mockGetSelfManagementBuiltInAgentProfile(...args),
  runSelfManagementBuiltInAgent: (...args: unknown[]) =>
    mockRunSelfManagementBuiltInAgent(...args),
  recoverSelfManagementBuiltInAgentInterrupts: (...args: unknown[]) =>
    mockRecoverSelfManagementBuiltInAgentInterrupts(...args),
  replySelfManagementBuiltInAgentPermissionInterrupt: (...args: unknown[]) =>
    mockReplySelfManagementBuiltInAgentPermissionInterrupt(...args),
  toPendingRuntimeInterrupt: (interrupt: {
    requestId: string;
    type: "permission";
    phase: "asked";
    details?: {
      permission?: string | null;
      patterns?: string[];
      displayMessage?: string | null;
    };
  }) => ({
    requestId: interrupt.requestId,
    type: interrupt.type,
    phase: interrupt.phase,
    details: {
      permission: interrupt.details?.permission ?? null,
      patterns: interrupt.details?.patterns ?? [],
      displayMessage: interrupt.details?.displayMessage ?? null,
    },
  }),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    info: (...args: unknown[]) => mockToastInfo(...args),
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

const renderChatScreen = (
  conversationId: string,
  agentId: string = "agent-1",
) => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ChatScreen agentId={agentId} conversationId={conversationId} />,
    );
  });
  return tree;
};

describe("ChatScreen interrupt handling", () => {
  const conversationId = "conversation-1";

  beforeEach(() => {
    mockAgentStoreState.activeAgentId = "agent-1";
    mockAddShortcut.mockReset().mockResolvedValue(undefined);
    mockUpdateShortcut.mockReset().mockResolvedValue(undefined);
    mockRemoveShortcut.mockReset().mockResolvedValue(undefined);
    mockReplyPermission.mockReset();
    mockReplyPermissions.mockReset();
    mockReplyQuestion.mockReset();
    mockRejectQuestion.mockReset();
    mockReplyElicitation.mockReset();
    mockAddConversationMessage.mockReset();
    mockMergeConversationMessages.mockReset();
    mockRemoveConversationMessage.mockReset();
    mockSetConversationMessages.mockReset();
    mockUpdateConversationMessage.mockReset();
    mockToastInfo.mockReset();
    mockToastSuccess.mockReset();
    mockToastError.mockReset();
    mockContinueSession.mockReset();
    mockListSessionMessagesPage.mockReset().mockResolvedValue({
      items: [],
      pageInfo: {
        hasMoreBefore: false,
        nextBefore: null,
      },
    });
    mockChatState.ensureSession.mockReset();
    mockChatState.generateConversationId
      .mockReset()
      .mockReturnValue("conversation-next");
    mockChatState.sendMessage.mockReset();
    mockChatState.cancelMessage.mockReset();
    mockChatState.clearPendingInterrupt.mockReset();
    mockChatState.replaceRecoveredInterrupts.mockReset();
    mockChatState.bindExternalSession.mockReset();
    mockChatState.setWorkingDirectory.mockReset();
    mockChatState.setInvokeMetadataBindings.mockReset();
    mockInvokeAgent.mockReset().mockResolvedValue({
      success: true,
      sessionControl: {
        intent: "append",
        status: "accepted",
        sessionId: "ses-upstream-1",
      },
    });
    mockInvokeHubAgent.mockReset().mockResolvedValue({ success: true });
    mockAppendSessionMessage.mockReset();
    mockRunSessionCommand.mockReset();
    mockGetSelfManagementBuiltInAgentProfile.mockReset().mockResolvedValue({
      id: SELF_MANAGEMENT_AGENT_ID,
      name: "A2A Client Hub Assistant",
      description: "Built-in self-management assistant",
      runtime: "swival",
      configured: true,
      resources: ["agents", "jobs", "sessions"],
      tools: [],
    });
    mockRunSelfManagementBuiltInAgent.mockReset().mockResolvedValue({
      status: "completed",
      answer: "Built-in agent reply",
      exhausted: false,
      runtime: "swival",
      resources: ["agents", "jobs", "sessions"],
      tools: ["self.jobs.list"],
      write_tools_enabled: false,
      interrupt: null,
    });
    mockRecoverSelfManagementBuiltInAgentInterrupts
      .mockReset()
      .mockResolvedValue({ items: [] });
    mockReplySelfManagementBuiltInAgentPermissionInterrupt
      .mockReset()
      .mockResolvedValue({
        status: "completed",
        answer: "Write approval was handled.",
        exhausted: false,
        runtime: "swival",
        resources: ["agents", "jobs", "sessions"],
        tools: ["self.jobs.pause"],
        write_tools_enabled: true,
        interrupt: null,
      });
    mockRecoverInterrupts.mockReset().mockResolvedValue({ items: [] });
    mockAddConversationMessage.mockReset();
    mockUpdateConversationMessage.mockReset();
    mockExtensionCapabilitiesState.modelSelectionStatus = "supported";
    mockExtensionCapabilitiesState.interruptRecoveryStatus = "supported";
    mockExtensionCapabilitiesState.sessionPromptAsyncStatus = "supported";
    mockExtensionCapabilitiesState.sessionCommandStatus = "supported";
    mockExtensionCapabilitiesState.sessionAppendStatus = "supported";
    mockExtensionCapabilitiesState.sessionAppend = {
      declared: true,
      consumedByHub: true,
      status: "supported",
      routeMode: "prompt_async",
      requiresStreamIdentity: false,
    };
    mockExtensionCapabilitiesState.invokeMetadataStatus = "unsupported";
    mockExtensionCapabilitiesState.invokeMetadata = null;
    mockExtensionCapabilitiesState.canShowModelPicker = true;
    mockSessionHistoryState.loadMore.mockReset();
    mockSessionHistoryState.messages = [];
    mockSessionHistoryState.error = null;
    mockSessionHistoryState.loading = false;
    mockSessionHistoryState.loadingMore = false;
    mockSessionHistoryState.nextPage = undefined;
    mockShortcutQueryState.shortcuts = [];
    mockShortcutQueryState.getShortcutsForAgent.mockClear();
    mockShortcutQueryState.getShortcutsForAgent.mockImplementation(
      (agentId: string | null) => {
        if (!agentId) {
          return mockShortcutQueryState.shortcuts.filter(
            (item) => !item.agentId,
          );
        }
        return mockShortcutQueryState.shortcuts.filter(
          (item) => !item.agentId || item.agentId === agentId,
        );
      },
    );
    mockContinueSession.mockResolvedValue({});
    mockReplyPermission.mockResolvedValue({ ok: true, requestId: "perm-1" });
    mockReplyPermissions.mockResolvedValue({ ok: true, requestId: "perms-1" });
    mockReplyQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
    mockRejectQuestion.mockResolvedValue({ ok: true, requestId: "q-1" });
    mockReplyElicitation.mockResolvedValue({ ok: true, requestId: "eli-1" });
    mockChatState.sessions = {
      [conversationId]: baseSession(),
    };
    global.requestAnimationFrame = ((callback: FrameRequestCallback) => {
      callback(0);
      return 0;
    }) as unknown as (callback: FrameRequestCallback) => number;
  });

  it("recovers pending interrupts for a bound upstream session", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      externalSessionRef: {
        provider: "opencode",
        externalSessionId: "sess-1",
      },
    };
    mockRecoverInterrupts.mockResolvedValue({
      items: [
        {
          requestId: "perm-1",
          sessionId: "sess-1",
          type: "permission",
          phase: "asked",
          source: "recovery",
          taskId: null,
          contextId: null,
          expiresAt: 120,
          details: {
            permission: "write",
            patterns: ["src/**"],
            displayMessage: "Approve write access",
          },
        },
      ],
    });

    renderChatScreen(conversationId);

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockRecoverInterrupts).toHaveBeenCalledWith({
      source: "personal",
      agentId: "agent-1",
      sessionId: "sess-1",
    });
    expect(mockChatState.replaceRecoveredInterrupts).toHaveBeenCalledWith(
      conversationId,
      [
        {
          requestId: "perm-1",
          sessionId: "sess-1",
          type: "permission",
          phase: "asked",
          source: "recovery",
          taskId: null,
          contextId: null,
          expiresAt: 120,
          details: {
            permission: "write",
            patterns: ["src/**"],
            displayMessage: "Approve write access",
          },
        },
      ],
      { sessionId: "sess-1" },
    );
  });

  it("recovers pending interrupts for the built-in agent from durable history", async () => {
    mockAgentStoreState.activeAgentId = SELF_MANAGEMENT_AGENT_ID;
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: SELF_MANAGEMENT_AGENT_ID,
    };
    mockRecoverSelfManagementBuiltInAgentInterrupts.mockResolvedValue({
      items: [
        {
          requestId: "perm-builtin-1",
          sessionId: conversationId,
          type: "permission",
          phase: "asked",
          source: "recovery",
          taskId: null,
          contextId: null,
          expiresAt: null,
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve pause access",
          },
        },
      ],
    });

    renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);

    await act(async () => {
      await Promise.resolve();
    });

    expect(
      mockRecoverSelfManagementBuiltInAgentInterrupts,
    ).toHaveBeenCalledWith({
      conversationId,
    });
    expect(mockRecoverInterrupts).not.toHaveBeenCalled();
    expect(mockChatState.replaceRecoveredInterrupts).toHaveBeenCalledWith(
      conversationId,
      [
        {
          requestId: "perm-builtin-1",
          sessionId: conversationId,
          type: "permission",
          phase: "asked",
          source: "recovery",
          taskId: null,
          contextId: null,
          expiresAt: null,
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve pause access",
          },
        },
      ],
      { sessionId: conversationId, replaceAllForConversation: true },
    );
  });

  it("disables sending and shows prompt when pending permission interrupt exists", () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "asked",
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
      root.findByProps({
        children:
          "Agent is waiting for authorization/input. Resolve the action card first.",
      }),
    ).toBeTruthy();
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
        phase: "asked",
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

  it("clears stale permission interrupts when the callback returns expiration", async () => {
    mockReplyPermission.mockRejectedValueOnce(
      new ApiRequestError("Conflict", 409, {
        errorCode: "interrupt_request_expired",
        upstreamError: {
          message: "Interrupt request expired",
        },
      }),
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-stale-1",
        type: "permission",
        phase: "asked",
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
      await Promise.resolve();
    });

    expect(mockChatState.clearPendingInterrupt).toHaveBeenCalledWith(
      conversationId,
      "perm-stale-1",
    );
    expect(mockToastInfo).toHaveBeenCalledWith(
      "Interrupt closed",
      "The interrupt request expired and was removed.",
    );
    expect(mockToastError).not.toHaveBeenCalled();
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
        phase: "asked",
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

  it("shows resolved interrupt feedback once for remotely resolved question events", () => {
    const tree = renderChatScreen(conversationId);
    const observedAt = new Date(Date.now() + 1_000).toISOString();

    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      lastResolvedInterrupt: {
        requestId: "q-1",
        type: "question",
        phase: "resolved",
        resolution: "replied",
        observedAt,
      },
    };

    act(() => {
      tree.update(
        <ChatScreen agentId="agent-1" conversationId={conversationId} />,
      );
    });

    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Interrupt resolved",
      "Question answer received. Agent resumed.",
    );

    act(() => {
      tree.update(
        <ChatScreen agentId="agent-1" conversationId={conversationId} />,
      );
    });

    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    act(() => {
      tree.unmount();
    });
  });

  it("does not duplicate resolved feedback after local permission reply succeeds", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "asked",
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
    const observedAt = new Date(Date.now() + 1_000).toISOString();

    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      lastResolvedInterrupt: {
        requestId: "perm-1",
        type: "permission",
        phase: "resolved",
        resolution: "replied",
        observedAt,
      },
    };

    act(() => {
      tree.update(
        <ChatScreen agentId="agent-1" conversationId={conversationId} />,
      );
    });

    expect(mockToastSuccess).toHaveBeenCalledTimes(1);
    act(() => {
      tree.unmount();
    });
  });

  it("shows the interrupt action card without requiring lifecycle history messages", () => {
    mockSessionHistoryState.messages = [];
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      pendingInterrupt: {
        requestId: "perm-2",
        type: "permission",
        phase: "asked",
        details: {
          permission: "read",
          patterns: ["/repo/.env"],
        },
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;

    expect(
      root.findByProps({
        children:
          "Agent is waiting for authorization/input. Resolve the action card first.",
      }),
    ).toBeTruthy();

    act(() => {
      tree.unmount();
    });
  });

  it("uses append as the default send action during streaming", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      workingDirectory: "/workspace/app",
      streamState: "streaming",
      externalSessionRef: {
        provider: "OpenCode",
        externalSessionId: "ses-upstream-1",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("append this");
    });
    mockAppendSessionMessage.mockResolvedValueOnce({
      conversationId,
      userMessage: {
        id: "append-user-1",
        role: "user",
        content: "append this",
        created_at: "2026-02-16T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
      sessionControl: {
        intent: "append",
        status: "accepted",
        sessionId: "ses-upstream-1",
      },
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockAppendSessionMessage).toHaveBeenCalledWith(conversationId, {
      content: "append this",
      userMessageId: expect.any(String),
      operationId: expect.any(String),
      metadata: {},
      workingDirectory: "/workspace/app",
    });
    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    expect(mockChatState.bindExternalSession).toHaveBeenCalledWith(
      conversationId,
      {
        agentId: "agent-1",
        externalSessionId: "ses-upstream-1",
      },
    );
    expect(mockAddConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        id: "append-user-1",
        role: "user",
        content: "append this",
      }),
    );
    expect(mockToastInfo).toHaveBeenCalledWith(
      "Message added to current response",
      "Your message was sent to the running upstream session.",
    );

    act(() => {
      tree.unmount();
    });
  });

  it("requires an explicit interrupt before sending when append is unavailable", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      streamState: "streaming",
      externalSessionRef: null,
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("new turn please");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockToastInfo).toHaveBeenCalledWith(
      "Interrupt required",
      "The agent is still working. Interrupt it before sending a new message.",
    );
    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    expect(mockInvokeAgent).not.toHaveBeenCalled();
    act(() => {
      tree.unmount();
    });
  });

  it("requires an explicit interrupt before sending when append capability is unsupported", async () => {
    mockExtensionCapabilitiesState.sessionPromptAsyncStatus = "unsupported";
    mockExtensionCapabilitiesState.sessionAppendStatus = "unsupported";
    mockExtensionCapabilitiesState.sessionAppend = {
      declared: false,
      consumedByHub: false,
      status: "unsupported",
      routeMode: "unsupported",
      requiresStreamIdentity: false,
    };
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      streamState: "streaming",
      externalSessionRef: {
        provider: "OpenCode",
        externalSessionId: "ses-upstream-3",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("capability fallback");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockToastInfo).toHaveBeenCalledWith(
      "Interrupt required",
      "The agent is still working. Interrupt it before sending a new message.",
    );
    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    expect(mockInvokeAgent).not.toHaveBeenCalled();
    act(() => {
      tree.unmount();
    });
  });

  it("uses append when the Hub append contract is supported via turn steering", async () => {
    mockExtensionCapabilitiesState.sessionPromptAsyncStatus = "unsupported";
    mockExtensionCapabilitiesState.sessionAppendStatus = "supported";
    mockExtensionCapabilitiesState.sessionAppend = {
      declared: true,
      consumedByHub: true,
      status: "supported",
      routeMode: "turn_steer",
      requiresStreamIdentity: true,
    };
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      streamState: "streaming",
      metadata: {
        shared: {
          stream: {
            thread_id: "thread-1",
            turn_id: "turn-1",
          },
        },
      },
      externalSessionRef: {
        provider: "Codex",
        externalSessionId: "ses-upstream-5",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("steer this");
    });
    mockAppendSessionMessage.mockResolvedValueOnce({
      conversationId,
      userMessage: {
        id: "append-user-2",
        role: "user",
        content: "steer this",
        created_at: "2026-02-16T00:01:00.000Z",
        status: "done",
        blocks: [],
      },
      sessionControl: {
        intent: "append",
        status: "accepted",
        sessionId: "ses-upstream-5",
      },
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockAppendSessionMessage).toHaveBeenCalledWith(conversationId, {
      content: "steer this",
      userMessageId: expect.any(String),
      operationId: expect.any(String),
      metadata: {
        shared: {
          stream: {
            thread_id: "thread-1",
            turn_id: "turn-1",
          },
        },
      },
    });
    expect(mockToastInfo).toHaveBeenCalledWith(
      "Message added to current response",
      "Your message was sent to the running upstream session.",
    );
    act(() => {
      tree.unmount();
    });
  });

  it("requires interrupt when the Hub append contract is unsupported", async () => {
    mockExtensionCapabilitiesState.sessionPromptAsyncStatus = "unsupported";
    mockExtensionCapabilitiesState.sessionAppendStatus = "unsupported";
    mockExtensionCapabilitiesState.sessionAppend = {
      declared: true,
      consumedByHub: true,
      status: "unsupported",
      routeMode: "unsupported",
      requiresStreamIdentity: false,
    };
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      streamState: "streaming",
      metadata: {
        shared: {
          stream: {
            thread_id: "thread-1",
            turn_id: "turn-1",
          },
        },
      },
      externalSessionRef: {
        provider: "Codex",
        externalSessionId: "ses-upstream-6",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("blocked steer");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockToastInfo).toHaveBeenCalledWith(
      "Interrupt required",
      "The agent is still working. Interrupt it before sending a new message.",
    );
    expect(mockInvokeAgent).not.toHaveBeenCalled();
    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    act(() => {
      tree.unmount();
    });
  });

  it("shows append failure without silently degrading to interrupt", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      workingDirectory: "/workspace/app",
      streamState: "streaming",
      externalSessionRef: {
        provider: "OpenCode",
        externalSessionId: "ses-upstream-4",
      },
    };
    mockAppendSessionMessage.mockRejectedValueOnce(
      new Error("append unavailable"),
    );

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("append attempt");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith(
      "Send failed",
      "append unavailable",
    );
    act(() => {
      tree.unmount();
    });
  });

  it("routes slash command input through session command when a bound upstream session exists", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      workingDirectory: "/workspace/app",
      externalSessionRef: {
        provider: "OpenCode",
        externalSessionId: "ses-upstream-4",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    mockRunSessionCommand.mockResolvedValueOnce({
      conversationId,
      userMessage: {
        id: "command-user-1",
        role: "user",
        content: "/review --quick\nFocus on tests",
        created_at: "2026-02-16T00:02:00.000Z",
        status: "done",
        blocks: [],
      },
      agentMessage: {
        id: "command-agent-1",
        role: "agent",
        content: "Done",
        created_at: "2026-02-16T00:02:01.000Z",
        status: "done",
        blocks: [],
      },
    });
    act(() => {
      input.props.onChangeText("/review --quick\nFocus on tests");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockRunSessionCommand).toHaveBeenCalledWith(conversationId, {
      command: "/review",
      arguments: "--quick",
      prompt: "Focus on tests",
      userMessageId: expect.any(String),
      agentMessageId: expect.any(String),
      operationId: expect.any(String),
      metadata: {},
      workingDirectory: "/workspace/app",
    });
    expect(mockAddConversationMessage).toHaveBeenCalledTimes(2);
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Command executed",
      "/review",
    );

    act(() => {
      tree.unmount();
    });
  });

  it("treats escaped slash input as a normal message", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      externalSessionRef: null,
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("//status");
    });
    await act(async () => {
      await sendButton.props.onPress();
    });

    expect(mockRunSessionCommand).not.toHaveBeenCalled();
    expect(mockChatState.sendMessage).toHaveBeenCalledWith(
      conversationId,
      "agent-1",
      "/status",
      "personal",
      undefined,
    );

    act(() => {
      tree.unmount();
    });
  });

  it("restores slash command input and shows an error when no upstream session is bound", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      externalSessionRef: null,
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("/status");
    });
    await act(async () => {
      await sendButton.props.onPress();
      await Promise.resolve();
    });

    expect(mockRunSessionCommand).not.toHaveBeenCalled();
    expect(mockChatState.sendMessage).not.toHaveBeenCalled();
    expect(mockToastError).toHaveBeenCalledWith(
      "Command unavailable",
      "This conversation is not bound to an upstream session yet.",
    );

    act(() => {
      tree.unmount();
    });
  });

  it("preempts the current stream through the invoke contract when the interrupt button is pressed", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      streamState: "streaming",
      externalSessionRef: {
        provider: "OpenCode",
        externalSessionId: "ses-upstream-9",
      },
    };

    const tree = renderChatScreen(conversationId);
    const root = tree.root;
    const interruptButton = root.findByProps({
      testID: "chat-interrupt-button",
    });

    mockInvokeAgent.mockResolvedValueOnce({
      success: true,
      sessionControl: {
        intent: "preempt",
        status: "completed",
      },
    });

    await act(async () => {
      await interruptButton.props.onPress();
    });

    expect(mockInvokeAgent).toHaveBeenCalledWith("agent-1", {
      query: "",
      conversationId,
      sessionControl: {
        intent: "preempt",
      },
      sessionBinding: {
        provider: "opencode",
        externalSessionId: "ses-upstream-9",
      },
    });
    expect(mockChatState.cancelMessage).toHaveBeenCalledWith(conversationId, {
      requestRemoteCancel: false,
    });
    expect(mockToastInfo).toHaveBeenCalledWith(
      "Response interrupted",
      "The current response was interrupted. You can send a new message now.",
    );
    act(() => {
      tree.unmount();
    });
  });

  it("routes built-in self-management runs into the existing permission interrupt UI", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: SELF_MANAGEMENT_AGENT_ID,
      externalSessionRef: null,
    };
    mockRunSelfManagementBuiltInAgent.mockResolvedValueOnce({
      status: "interrupted",
      answer: "I can pause that job after write approval.",
      exhausted: false,
      runtime: "swival",
      resources: ["agents", "jobs", "sessions"],
      tools: ["self.jobs.list", "self.jobs.pause"],
      write_tools_enabled: false,
      interrupt: {
        requestId: "builtin-perm-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "self-management-write",
          patterns: ["self.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
    });

    const tree = renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);
    const root = tree.root;
    const input = root.findByProps({ placeholder: "Type your message" });
    const sendButton = root.findByProps({ testID: "chat-send-button" });

    act(() => {
      input.props.onChangeText("Pause my job");
    });
    await act(async () => {
      await sendButton.props.onPress();
      await Promise.resolve();
    });

    expect(mockRunSelfManagementBuiltInAgent).toHaveBeenCalledWith({
      conversationId,
      message: "Pause my job",
      userMessageId: expect.any(String),
      agentMessageId: expect.any(String),
    });
    expect(mockAddConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        role: "user",
        content: "Pause my job",
      }),
    );
    expect(mockAddConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        role: "agent",
        content: "",
        status: "streaming",
      }),
    );
    expect(mockUpdateConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.any(String),
      expect.objectContaining({
        content: "I can pause that job after write approval.",
        status: "interrupted",
      }),
    );
    expect(
      mockChatState.sessions[conversationId]?.pendingInterrupt,
    ).toMatchObject({
      requestId: "builtin-perm-1",
      type: "permission",
      phase: "asked",
      details: {
        permission: "self-management-write",
        patterns: ["self.jobs.pause"],
        displayMessage: "Approve write access to continue.",
      },
    });

    act(() => {
      tree.unmount();
    });
  });

  it.each([
    {
      buttonTestId: "interrupt-permission-once",
      reply: "once" as const,
      expectedResolution: "replied",
    },
    {
      buttonTestId: "interrupt-permission-always",
      reply: "always" as const,
      expectedResolution: "replied",
    },
    {
      buttonTestId: "interrupt-permission-reject",
      reply: "reject" as const,
      expectedResolution: "rejected",
    },
  ])(
    "submits built-in permission reply %s through the existing interrupt action card",
    async ({ buttonTestId, reply, expectedResolution }) => {
      mockChatState.sessions[conversationId] = {
        ...baseSession(),
        agentId: SELF_MANAGEMENT_AGENT_ID,
        pendingInterrupt: {
          requestId: "builtin-perm-2",
          type: "permission",
          phase: "asked",
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
        pendingInterrupts: [
          {
            requestId: "builtin-perm-2",
            type: "permission",
            phase: "asked",
            details: {
              permission: "self-management-write",
              patterns: ["self.jobs.pause"],
              displayMessage: "Approve write access to continue.",
            },
          },
        ],
      };

      const tree = renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);
      const root = tree.root;
      const permissionButton = root.findByProps({
        testID: buttonTestId,
      });

      await act(async () => {
        await permissionButton.props.onPress();
        await Promise.resolve();
      });

      expect(
        mockReplySelfManagementBuiltInAgentPermissionInterrupt,
      ).toHaveBeenCalledWith({
        requestId: "builtin-perm-2",
        reply,
        agentMessageId: expect.any(String),
      });
      expect(mockAddConversationMessage).toHaveBeenCalledWith(
        conversationId,
        expect.objectContaining({
          role: "agent",
          content: "",
          status: "streaming",
        }),
      );
      expect(mockUpdateConversationMessage).toHaveBeenCalledWith(
        conversationId,
        expect.any(String),
        expect.objectContaining({
          content: "Write approval was handled.",
          status: "done",
        }),
      );
      expect(
        mockChatState.sessions[conversationId]?.pendingInterrupt,
      ).toBeNull();
      expect(
        mockChatState.sessions[conversationId]?.lastResolvedInterrupt,
      ).toMatchObject({
        requestId: "builtin-perm-2",
        type: "permission",
        phase: "resolved",
        resolution: expectedResolution,
      });
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Action submitted",
        "Authorization request handled.",
      );

      act(() => {
        tree.unmount();
      });
    },
  );

  it("closes the built-in authorization card on fast-ack and enters continuation state", async () => {
    mockReplySelfManagementBuiltInAgentPermissionInterrupt.mockImplementationOnce(
      async (payload: { agentMessageId: string }) => {
        return {
          status: "accepted",
          answer: null,
          exhausted: false,
          runtime: "swival",
          resources: ["agents", "jobs", "sessions"],
          tools: ["self.jobs.pause"],
          write_tools_enabled: true,
          interrupt: null,
          continuation: {
            phase: "running",
            agentMessageId: payload.agentMessageId,
          },
        };
      },
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: SELF_MANAGEMENT_AGENT_ID,
      pendingInterrupt: {
        requestId: "builtin-perm-async-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "self-management-write",
          patterns: ["self.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "builtin-perm-async-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);
    const root = tree.root;
    const permissionButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      await permissionButton.props.onPress();
      await Promise.resolve();
    });

    expect(
      mockReplySelfManagementBuiltInAgentPermissionInterrupt,
    ).toHaveBeenCalledWith({
      requestId: "builtin-perm-async-1",
      reply: "once",
      agentMessageId: expect.any(String),
    });
    expect(mockChatState.sessions[conversationId]?.pendingInterrupt).toBeNull();
    expect(mockChatState.sessions[conversationId]?.streamState).toBe(
      "continuing",
    );
    expect(
      mockChatState.sessions[conversationId]?.lastResolvedInterrupt,
    ).toMatchObject({
      requestId: "builtin-perm-async-1",
      type: "permission",
      phase: "resolved",
      resolution: "replied",
    });
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Action submitted",
      "Authorization request handled.",
    );

    act(() => {
      tree.unmount();
    });
  });

  it("clears stale built-in permission interrupts when the reply request expired", async () => {
    mockReplySelfManagementBuiltInAgentPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Bad Request", 400, {
        errorCode: "interrupt_request_expired",
        upstreamError: {
          message: "The write approval request is invalid or expired.",
        },
      }),
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: SELF_MANAGEMENT_AGENT_ID,
      pendingInterrupt: {
        requestId: "builtin-perm-stale-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "self-management-write",
          patterns: ["self.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "builtin-perm-stale-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);
    const root = tree.root;
    const permissionButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      await permissionButton.props.onPress();
      await Promise.resolve();
    });

    expect(
      mockReplySelfManagementBuiltInAgentPermissionInterrupt,
    ).toHaveBeenCalledWith({
      requestId: "builtin-perm-stale-1",
      reply: "once",
      agentMessageId: expect.any(String),
    });
    expect(mockChatState.clearPendingInterrupt).toHaveBeenCalledWith(
      conversationId,
      "builtin-perm-stale-1",
    );
    expect(mockRemoveConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.any(String),
    );
    expect(mockUpdateConversationMessage).not.toHaveBeenCalled();
    expect(mockChatState.sessions[conversationId]?.streamState).toBe("idle");
    expect(mockChatState.sessions[conversationId]?.lastStreamError).toBeNull();
    expect(mockToastInfo).toHaveBeenCalledWith(
      "Interrupt closed",
      "The interrupt request expired and was removed.",
    );
    expect(mockToastError).not.toHaveBeenCalled();

    act(() => {
      tree.unmount();
    });
  });

  it("restores built-in permission reply state after non-terminal errors", async () => {
    mockReplySelfManagementBuiltInAgentPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Server Error", 500, {
        errorCode: "internal_error",
        upstreamError: {
          message: "Permission reply failed upstream.",
        },
      }),
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: SELF_MANAGEMENT_AGENT_ID,
      pendingInterrupt: {
        requestId: "builtin-perm-failed-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "self-management-write",
          patterns: ["self.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "builtin-perm-failed-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "self-management-write",
            patterns: ["self.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, SELF_MANAGEMENT_AGENT_ID);
    const root = tree.root;
    const permissionButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      await permissionButton.props.onPress();
      await Promise.resolve();
    });

    expect(mockRemoveConversationMessage).toHaveBeenCalledWith(
      conversationId,
      expect.any(String),
    );
    expect(mockUpdateConversationMessage).not.toHaveBeenCalled();
    expect(mockChatState.clearPendingInterrupt).not.toHaveBeenCalled();
    expect(mockChatState.sessions[conversationId]?.streamState).toBe("idle");
    expect(mockChatState.sessions[conversationId]?.lastStreamError).toBeNull();
    expect(mockToastError).toHaveBeenCalledWith(
      "Interrupt callback failed",
      "Server Error [internal_error]：Permission reply failed upstream.",
    );

    act(() => {
      tree.unmount();
    });
  });
});
