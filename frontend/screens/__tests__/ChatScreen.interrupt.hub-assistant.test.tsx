import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  cleanupChatScreenInterruptTree,
  resetChatScreenInterruptHarness,
} from "./ChatScreen.interrupt.test.common";

import { ApiRequestError } from "@/lib/api/client";
import { ChatScreen } from "@/screens/ChatScreen";

const HUB_ASSISTANT_AGENT_ID = "hub-assistant";

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
const mockGetHubAssistantProfile = jest.fn();
const mockRunHubAssistant = jest.fn();
const mockRecoverHubAssistantPermissionInterrupts = jest.fn();
const mockReplyHubAssistantPermissionInterrupt = jest.fn();
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
              Agent is waiting for permission/input. Resolve the action card
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
        id: HUB_ASSISTANT_AGENT_ID,
        source: "hub_assistant",
        name: "A2A Client Hub Assistant",
        cardUrl: "hub-assistant://hub-assistant",
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

jest.mock("@/lib/api/hubAssistant", () => ({
  HUB_ASSISTANT_ID: HUB_ASSISTANT_AGENT_ID,
  isHubAssistant: (agentId?: string | null) =>
    (agentId ?? "").trim() === HUB_ASSISTANT_AGENT_ID,
  getHubAssistantProfile: (...args: unknown[]) =>
    mockGetHubAssistantProfile(...args),
  runHubAssistant: (...args: unknown[]) => mockRunHubAssistant(...args),
  recoverHubAssistantPermissionInterrupts: (...args: unknown[]) =>
    mockRecoverHubAssistantPermissionInterrupts(...args),
  replyHubAssistantPermissionInterrupt: (...args: unknown[]) =>
    mockReplyHubAssistantPermissionInterrupt(...args),
  toPendingRuntimePermissionInterrupt: (interrupt: {
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

let renderedTree: ReactTestRenderer | null = null;

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
  const originalUnmount = tree.unmount.bind(tree);
  tree.unmount = () => {
    originalUnmount();
    if (renderedTree === tree) {
      renderedTree = null;
    }
  };
  renderedTree = tree;
  return tree;
};

describe("ChatScreen interrupt handling", () => {
  const conversationId = "conversation-1";

  beforeEach(() => {
    resetChatScreenInterruptHarness({
      conversationId,
      hubAssistantAgentId: HUB_ASSISTANT_AGENT_ID,
      baseSession,
      mockAgentStoreState,
      mockChatState,
      mockExtensionCapabilitiesState,
      mockSessionHistoryState,
      mockShortcutQueryState,
      mockAddShortcut,
      mockUpdateShortcut,
      mockRemoveShortcut,
      mockReplyPermission,
      mockReplyPermissions,
      mockReplyQuestion,
      mockRejectQuestion,
      mockReplyElicitation,
      mockAppendSessionMessage,
      mockListSessionMessagesPage,
      mockRunSessionCommand,
      mockRecoverInterrupts,
      mockInvokeAgent,
      mockInvokeHubAgent,
      mockGetHubAssistantProfile,
      mockRunHubAssistant,
      mockRecoverHubAssistantPermissionInterrupts,
      mockReplyHubAssistantPermissionInterrupt,
      mockAddConversationMessage,
      mockMergeConversationMessages,
      mockRemoveConversationMessage,
      mockSetConversationMessages,
      mockUpdateConversationMessage,
      mockToastInfo,
      mockToastSuccess,
      mockToastError,
      mockContinueSession,
    });
  });

  afterEach(() => {
    renderedTree = cleanupChatScreenInterruptTree(renderedTree);
  });

  it("routes Hub Assistant hub-assistant runs into the existing permission interrupt UI", async () => {
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: HUB_ASSISTANT_AGENT_ID,
      externalSessionRef: null,
    };
    mockRunHubAssistant.mockResolvedValueOnce({
      status: "interrupted",
      answer: "I can pause that job after write approval.",
      exhausted: false,
      runtime: "swival",
      resources: ["agents", "jobs", "sessions"],
      tools: ["hub_assistant.jobs.list", "hub_assistant.jobs.pause"],
      write_tools_enabled: false,
      interrupt: {
        requestId: "hub_assistant-perm-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "hub-assistant-write",
          patterns: ["hub_assistant.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
    });

    const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
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

    expect(mockRunHubAssistant).toHaveBeenCalledWith({
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
      requestId: "hub_assistant-perm-1",
      type: "permission",
      phase: "asked",
      details: {
        permission: "hub-assistant-write",
        patterns: ["hub_assistant.jobs.pause"],
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
    "submits Hub Assistant permission reply %s through the existing interrupt action card",
    async ({ buttonTestId, reply, expectedResolution }) => {
      mockChatState.sessions[conversationId] = {
        ...baseSession(),
        agentId: HUB_ASSISTANT_AGENT_ID,
        pendingInterrupt: {
          requestId: "hub_assistant-perm-2",
          type: "permission",
          phase: "asked",
          details: {
            permission: "hub-assistant-write",
            patterns: ["hub_assistant.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
        pendingInterrupts: [
          {
            requestId: "hub_assistant-perm-2",
            type: "permission",
            phase: "asked",
            details: {
              permission: "hub-assistant-write",
              patterns: ["hub_assistant.jobs.pause"],
              displayMessage: "Approve write access to continue.",
            },
          },
        ],
      };

      const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
      const root = tree.root;
      const permissionButton = root.findByProps({
        testID: buttonTestId,
      });

      await act(async () => {
        await permissionButton.props.onPress();
        await Promise.resolve();
      });

      expect(mockReplyHubAssistantPermissionInterrupt).toHaveBeenCalledWith({
        requestId: "hub_assistant-perm-2",
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
        requestId: "hub_assistant-perm-2",
        type: "permission",
        phase: "resolved",
        resolution: expectedResolution,
      });
      expect(mockToastSuccess).toHaveBeenCalledWith(
        "Action submitted",
        "Permission request handled.",
      );

      act(() => {
        tree.unmount();
      });
    },
  );

  it("closes the Hub Assistant permission card on fast-ack and enters continuation state", async () => {
    mockReplyHubAssistantPermissionInterrupt.mockImplementationOnce(
      async (payload: { agentMessageId: string }) => {
        return {
          status: "accepted",
          answer: null,
          exhausted: false,
          runtime: "swival",
          resources: ["agents", "jobs", "sessions"],
          tools: ["hub_assistant.jobs.pause"],
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
      agentId: HUB_ASSISTANT_AGENT_ID,
      pendingInterrupt: {
        requestId: "hub_assistant-perm-async-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "hub-assistant-write",
          patterns: ["hub_assistant.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "hub_assistant-perm-async-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "hub-assistant-write",
            patterns: ["hub_assistant.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
    const root = tree.root;
    const permissionButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      await permissionButton.props.onPress();
      await Promise.resolve();
    });

    expect(mockReplyHubAssistantPermissionInterrupt).toHaveBeenCalledWith({
      requestId: "hub_assistant-perm-async-1",
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
      requestId: "hub_assistant-perm-async-1",
      type: "permission",
      phase: "resolved",
      resolution: "replied",
    });
    expect(mockToastSuccess).toHaveBeenCalledWith(
      "Action submitted",
      "Permission request handled.",
    );

    act(() => {
      tree.unmount();
    });
  });

  it("keeps waiting for persisted continuation state instead of forcing a timeout error", async () => {
    jest.useFakeTimers();
    try {
      mockReplyHubAssistantPermissionInterrupt.mockImplementationOnce(
        async (payload: { agentMessageId: string }) => {
          return {
            status: "accepted",
            answer: null,
            exhausted: false,
            runtime: "swival",
            resources: ["agents", "jobs", "sessions"],
            tools: ["hub_assistant.jobs.pause"],
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
        agentId: HUB_ASSISTANT_AGENT_ID,
        pendingInterrupt: {
          requestId: "hub_assistant-perm-async-2",
          type: "permission",
          phase: "asked",
          details: {
            permission: "hub-assistant-write",
            patterns: ["hub_assistant.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
        pendingInterrupts: [
          {
            requestId: "hub_assistant-perm-async-2",
            type: "permission",
            phase: "asked",
            details: {
              permission: "hub-assistant-write",
              patterns: ["hub_assistant.jobs.pause"],
              displayMessage: "Approve write access to continue.",
            },
          },
        ],
      };

      const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
      const root = tree.root;
      const permissionButton = root.findByProps({
        testID: "interrupt-permission-once",
      });

      await act(async () => {
        await permissionButton.props.onPress();
        await Promise.resolve();
        await Promise.resolve();
      });

      mockUpdateConversationMessage.mockClear();

      await act(async () => {
        jest.advanceTimersByTime(60_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(mockChatState.sessions[conversationId]?.streamState).toBe(
        "continuing",
      );
      expect(mockUpdateConversationMessage).not.toHaveBeenCalledWith(
        conversationId,
        expect.any(String),
        expect.objectContaining({
          content:
            "Hub Assistant continuation timed out while waiting for persisted output.",
          status: "error",
        }),
      );

      act(() => {
        tree.unmount();
      });
    } finally {
      jest.useRealTimers();
    }
  });

  it("refreshes an idle Hub Assistant chat so proactive follow-up replies become visible", async () => {
    jest.useFakeTimers();
    try {
      mockChatState.sessions[conversationId] = {
        ...baseSession(),
        agentId: HUB_ASSISTANT_AGENT_ID,
        streamState: "idle",
      };
      mockListSessionMessagesPage.mockResolvedValue({
        items: [
          {
            id: "auto-follow-up-1",
            role: "agent",
            kind: "message",
            content: "I checked and here is the result.",
            created_at: "2026-04-16T05:00:00.000Z",
            status: "done",
            operationId: null,
            blocks: [],
          },
        ],
        pageInfo: {
          hasMoreBefore: false,
          nextBefore: null,
        },
      });

      const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);

      await act(async () => {
        jest.advanceTimersByTime(5_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(mockListSessionMessagesPage).toHaveBeenCalledWith(conversationId, {
        before: null,
        limit: 8,
      });
      expect(mockMergeConversationMessages).toHaveBeenCalledWith(
        conversationId,
        [
          expect.objectContaining({
            id: "auto-follow-up-1",
            role: "agent",
            content: "I checked and here is the result.",
            status: "done",
          }),
        ],
      );

      act(() => {
        tree.unmount();
      });
    } finally {
      jest.useRealTimers();
    }
  });

  it("does not re-run Hub Assistant interrupt recovery when only historical agent messages are interrupted", async () => {
    jest.useFakeTimers();
    try {
      mockChatState.sessions[conversationId] = {
        ...baseSession(),
        agentId: HUB_ASSISTANT_AGENT_ID,
        streamState: "idle",
      };
      mockListSessionMessagesPage.mockResolvedValue({
        items: [
          {
            id: "agent-done-latest",
            role: "agent",
            kind: "message",
            content: "Both delegated reviews have completed.",
            created_at: "2026-04-16T10:04:06.930Z",
            status: "done",
            operationId: null,
            blocks: [],
          },
          {
            id: "agent-old-interrupted",
            role: "agent",
            kind: "message",
            content: "Waiting for approval.",
            created_at: "2026-04-16T10:03:44.421Z",
            status: "interrupted",
            operationId: null,
            blocks: [],
          },
        ],
        pageInfo: {
          hasMoreBefore: false,
          nextBefore: null,
        },
      });

      const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);

      await act(async () => {
        await Promise.resolve();
      });
      mockRecoverHubAssistantPermissionInterrupts.mockClear();

      await act(async () => {
        jest.advanceTimersByTime(5_000);
        await Promise.resolve();
        await Promise.resolve();
      });

      expect(mockListSessionMessagesPage).toHaveBeenCalledWith(conversationId, {
        before: null,
        limit: 8,
      });
      expect(
        mockRecoverHubAssistantPermissionInterrupts,
      ).not.toHaveBeenCalled();

      act(() => {
        tree.unmount();
      });
    } finally {
      jest.useRealTimers();
    }
  });

  it("clears stale Hub Assistant permission interrupts when the reply request expired", async () => {
    mockReplyHubAssistantPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Bad Request", 400, {
        errorCode: "interrupt_request_expired",
        upstreamError: {
          message: "The write approval request is invalid or expired.",
        },
      }),
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: HUB_ASSISTANT_AGENT_ID,
      pendingInterrupt: {
        requestId: "hub_assistant-perm-stale-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "hub-assistant-write",
          patterns: ["hub_assistant.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "hub_assistant-perm-stale-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "hub-assistant-write",
            patterns: ["hub_assistant.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
    const root = tree.root;
    const permissionButton = root.findByProps({
      testID: "interrupt-permission-once",
    });

    await act(async () => {
      await permissionButton.props.onPress();
      await Promise.resolve();
    });

    expect(mockReplyHubAssistantPermissionInterrupt).toHaveBeenCalledWith({
      requestId: "hub_assistant-perm-stale-1",
      reply: "once",
      agentMessageId: expect.any(String),
    });
    expect(mockChatState.clearPendingInterrupt).toHaveBeenCalledWith(
      conversationId,
      "hub_assistant-perm-stale-1",
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

  it("restores Hub Assistant permission reply state after non-terminal errors", async () => {
    mockReplyHubAssistantPermissionInterrupt.mockRejectedValueOnce(
      new ApiRequestError("Server Error", 500, {
        errorCode: "internal_error",
        upstreamError: {
          message: "Permission reply failed upstream.",
        },
      }),
    );
    mockChatState.sessions[conversationId] = {
      ...baseSession(),
      agentId: HUB_ASSISTANT_AGENT_ID,
      pendingInterrupt: {
        requestId: "hub_assistant-perm-failed-1",
        type: "permission",
        phase: "asked",
        details: {
          permission: "hub-assistant-write",
          patterns: ["hub_assistant.jobs.pause"],
          displayMessage: "Approve write access to continue.",
        },
      },
      pendingInterrupts: [
        {
          requestId: "hub_assistant-perm-failed-1",
          type: "permission",
          phase: "asked",
          details: {
            permission: "hub-assistant-write",
            patterns: ["hub_assistant.jobs.pause"],
            displayMessage: "Approve write access to continue.",
          },
        },
      ],
    };

    const tree = renderChatScreen(conversationId, HUB_ASSISTANT_AGENT_ID);
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
