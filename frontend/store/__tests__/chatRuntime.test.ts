import {
  listSessionMessagesPage,
  type SessionMessageItem,
} from "@/lib/api/sessions";
import { createAgentSession } from "@/lib/chat-utils";
import {
  addConversationMessage,
  clearAllConversationMessages,
  getConversationMessages,
} from "@/lib/chatHistoryCache";
import { chatConnectionService } from "@/services/chatConnectionService";
import { queryClient } from "@/services/queryClient";
import {
  executeChatRuntime,
  type ChatRuntimeSetState,
  type ChatRuntimeState,
} from "@/store/chatRuntime";

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    isWsHealthy: jest.fn(() => true),
    isSseHealthy: jest.fn(() => false),
    tryWebSocketTransport: jest.fn(async () => false),
    trySseTransport: jest.fn(async () => false),
  },
}));

jest.mock("@/lib/api/sessions", () => ({
  listSessionMessagesPage: jest.fn(),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  invokeAgent: jest.fn(async () => ({ success: true, content: "" })),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  invokeHubAgent: jest.fn(async () => ({ success: true, content: "" })),
}));

const mockedListSessionMessagesPage =
  listSessionMessagesPage as jest.MockedFunction<
    typeof listSessionMessagesPage
  >;
const mockedChatConnectionService = chatConnectionService as jest.Mocked<
  typeof chatConnectionService
>;

const flushPromises = async () => {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
};

const createDeferred = <T>() => {
  let resolve: ((value: T) => void) | null = null;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return {
    promise,
    resolve: (value: T) => {
      if (resolve) {
        resolve(value);
      }
    },
  };
};

describe("executeChatRuntime empty-content recovery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    queryClient.clear();
    clearAllConversationMessages();
  });

  it("keeps session streaming until one-time history backfill completes", async () => {
    const conversationId = "conv-recovery-1";
    const agentId = "agent-1";
    const userMessageId = "user-msg-1";
    const agentMessageId = "agent-msg-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T05:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T05:00:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    const deferred = createDeferred<{
      items: SessionMessageItem[];
      pageInfo: { hasMoreBefore: boolean; nextBefore: null };
    }>();
    mockedListSessionMessagesPage.mockReturnValueOnce(deferred.promise);

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
        });
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(mockedListSessionMessagesPage).toHaveBeenCalledWith(conversationId, {
      before: null,
      limit: 20,
    });
    expect(state.sessions[conversationId]?.streamState).toBe("streaming");
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      )?.status,
    ).toBe("streaming");

    deferred.resolve({
      items: [
        {
          id: agentMessageId,
          role: "agent",
          created_at: "2026-03-12T05:00:01.000Z",
          status: "done",
          blocks: [
            {
              id: "blk-1",
              type: "text",
              content: "Recovered response",
              isFinished: true,
            },
          ],
        },
      ],
      pageInfo: {
        hasMoreBefore: false,
        nextBefore: null,
      },
    });
    await flushPromises();

    expect(state.sessions[conversationId]?.streamState).toBe("idle");
    const agentMessage = getConversationMessages(conversationId).find(
      (message) => message.id === agentMessageId,
    );
    expect(agentMessage?.status).toBe("done");
    expect(agentMessage?.content).toBe("Recovered response");
  });

  it("renders compatible text chunks during stream without empty-content recovery", async () => {
    const conversationId = "conv-stream-compat-1";
    const agentId = "agent-compat-1";
    const userMessageId = "user-msg-compat-1";
    const agentMessageId = "agent-msg-compat-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T06:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T06:00:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    let renderedDuringStream = false;
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
        });
        params.callbacks.onData({
          kind: "artifact-update",
          taskId: "task-compat-1",
          append: true,
          artifact: {
            artifactId: "stream-compat-1",
            parts: [{ type: "text", content: "Hello from stream" }],
          },
        });
        await new Promise((resolve) => setTimeout(resolve, 30));
        renderedDuringStream = getConversationMessages(conversationId).some(
          (message) =>
            message.role === "agent" &&
            message.status === "streaming" &&
            message.content.includes("Hello from stream"),
        );
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(renderedDuringStream).toBe(true);
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();

    const messages = getConversationMessages(conversationId);
    const streamedAgentMessage = messages.find(
      (message) =>
        message.role === "agent" &&
        message.content.includes("Hello from stream"),
    );
    expect(streamedAgentMessage?.status).toBe("done");
  });

  it("renders a tool_call placeholder during stream before any text block arrives", async () => {
    const conversationId = "conv-stream-tool-call-1";
    const agentId = "agent-tool-call-1";
    const userMessageId = "user-msg-tool-call-1";
    const agentMessageId = "agent-msg-tool-call-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T06:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T06:10:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    let renderedDuringStream = false;
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
        });
        params.callbacks.onData({
          kind: "artifact-update",
          append: false,
          message_id: agentMessageId,
          event_id: `${agentMessageId}:1`,
          seq: 1,
          artifact: {
            artifactId: `${agentMessageId}:stream`,
            parts: [
              {
                kind: "data",
                data: {
                  call_id: "call-1",
                  tool: "bash",
                  status: "running",
                  input: { command: "pwd" },
                },
              },
            ],
            metadata: {
              shared: {
                stream: {
                  block_type: "tool_call",
                  source: "tool_part_update",
                  message_id: agentMessageId,
                  event_id: `${agentMessageId}:1`,
                  sequence: 1,
                },
              },
            },
          },
        });

        const agentMessage = getConversationMessages(conversationId).find(
          (message) => message.id === agentMessageId,
        );
        renderedDuringStream =
          agentMessage?.status === "streaming" &&
          (agentMessage.blocks?.length ?? 0) > 0 &&
          agentMessage?.blocks?.[0]?.type === "tool_call";

        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(renderedDuringStream).toBe(true);
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
  });

  it("renders a reasoning placeholder during stream before completion", async () => {
    const conversationId = "conv-stream-reasoning-1";
    const agentId = "agent-reasoning-1";
    const userMessageId = "user-msg-reasoning-1";
    const agentMessageId = "agent-msg-reasoning-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T06:20:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T06:20:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    let renderedDuringStream = false;
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
        });
        params.callbacks.onData({
          kind: "artifact-update",
          append: false,
          message_id: agentMessageId,
          event_id: `${agentMessageId}:1`,
          seq: 1,
          artifact: {
            artifactId: `${agentMessageId}:stream`,
            parts: [{ kind: "text", text: "Reasoning in progress" }],
            metadata: {
              shared: {
                stream: {
                  block_type: "reasoning",
                  source: "reasoning_part_update",
                  message_id: agentMessageId,
                  event_id: `${agentMessageId}:1`,
                  sequence: 1,
                },
              },
            },
          },
        });

        const agentMessage = getConversationMessages(conversationId).find(
          (message) => message.id === agentMessageId,
        );
        renderedDuringStream =
          agentMessage?.status === "streaming" &&
          (agentMessage.blocks?.length ?? 0) > 0 &&
          agentMessage?.blocks?.[0]?.type === "reasoning";

        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(renderedDuringStream).toBe(true);
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
  });

  it("keeps pending interrupt until a matching resolved event arrives", async () => {
    const conversationId = "conv-interrupt-pending-1";
    const agentId = "agent-interrupt-1";
    const userMessageId = "user-msg-interrupt-1";
    const agentMessageId = "agent-msg-interrupt-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T07:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T07:00:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    let pendingAfterWorking = state.sessions[conversationId]?.pendingInterrupt;
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "input-required" },
          final: false,
          metadata: {
            interrupt: {
              request_id: "perm-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          },
        });
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
        });
        pendingAfterWorking = state.sessions[conversationId]?.pendingInterrupt;
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(pendingAfterWorking).toMatchObject({
      requestId: "perm-1",
      type: "permission",
      phase: "asked",
    });
    expect(state.sessions[conversationId]?.pendingInterrupt).toBeNull();
    expect(state.sessions[conversationId]?.lastResolvedInterrupt).toBeNull();
  });

  it("records resolved interrupt state and only clears matching pending interrupt", async () => {
    const conversationId = "conv-interrupt-resolved-1";
    const agentId = "agent-interrupt-2";
    const userMessageId = "user-msg-interrupt-2";
    const agentMessageId = "agent-msg-interrupt-2";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T08:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T08:00:01.000Z",
      status: "streaming",
    });

    let state: ChatRuntimeState = {
      sessions: {
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          pendingInterrupt: {
            requestId: "perm-1",
            type: "permission",
            phase: "asked",
            details: {
              permission: "read",
              patterns: ["/repo/.env"],
            },
          },
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
        },
      },
    };

    const get = () => state;
    const set: ChatRuntimeSetState<ChatRuntimeState> = (partial) => {
      const next =
        typeof partial === "function"
          ? partial(state as ChatRuntimeState)
          : partial;
      state = {
        ...state,
        ...(next as Partial<ChatRuntimeState>),
      };
    };

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
          metadata: {
            interrupt: {
              request_id: "q-other",
              type: "question",
              phase: "resolved",
              resolution: "rejected",
            },
          },
        });
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "working" },
          final: false,
          metadata: {
            interrupt: {
              request_id: "perm-1",
              type: "permission",
              phase: "resolved",
              resolution: "replied",
            },
          },
        });
        params.callbacks.onData({
          kind: "status-update",
          status: { state: "completed" },
          final: true,
        });
        return true;
      },
    );

    await executeChatRuntime(
      conversationId,
      agentId,
      "personal",
      {
        query: "hello",
        conversationId,
        userMessageId,
        agentMessageId,
      },
      agentMessageId,
      get,
      set,
    );

    expect(state.sessions[conversationId]?.pendingInterrupt).toBeNull();
    expect(state.sessions[conversationId]?.lastResolvedInterrupt).toMatchObject(
      {
        requestId: "perm-1",
        type: "permission",
        phase: "resolved",
        resolution: "replied",
      },
    );
  });
});
