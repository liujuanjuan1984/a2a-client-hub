import { getConversationMessages } from "@/lib/chatHistoryCache";
import { useChatStore } from "@/store/chat";
import { executeChatRuntime } from "@/store/chatRuntime";

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    cancelSession: jest.fn(async () => {}),
    getPreferredTransport: jest.fn(() => "http_json"),
    clearAll: jest.fn(),
  },
}));

jest.mock("@/store/chatRuntime", () => ({
  executeChatRuntime: jest.fn(async () => {}),
}));

const mockedExecuteChatRuntime = executeChatRuntime as jest.MockedFunction<
  typeof executeChatRuntime
>;
const {
  chatConnectionService,
}: {
  chatConnectionService: {
    cancelSession: jest.Mock;
  };
} = require("@/services/chatConnectionService");

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("chat store idempotency semantics", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useChatStore.getState().clearAll();
  });

  it("sendMessage creates UUID message ids and forwards userMessageId", async () => {
    await useChatStore
      .getState()
      .sendMessage("conv-1", "agent-1", "hello world", "personal");

    const messages = getConversationMessages("conv-1");
    expect(messages).toHaveLength(2);

    const userMessage = messages.find((message) => message.role === "user");
    const agentMessage = messages.find((message) => message.role === "agent");

    expect(userMessage).toBeDefined();
    expect(agentMessage).toBeDefined();

    expect(userMessage?.id).toMatch(UUID_V4_PATTERN);
    expect(agentMessage?.id).toMatch(UUID_V4_PATTERN);

    const session = useChatStore.getState().sessions["conv-1"];
    expect(session?.lastUserMessageId).toBe(userMessage?.id);
    expect(session?.lastAgentMessageId).toBe(agentMessage?.id);

    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const runtimeCall = mockedExecuteChatRuntime.mock.calls[0];
    expect(runtimeCall?.[0]).toBe("conv-1");
    expect(runtimeCall?.[1]).toBe("agent-1");
    expect(runtimeCall?.[2]).toBe("personal");
    expect(runtimeCall?.[3]).toMatchObject({
      query: "hello world",
      conversationId: "conv-1",
      userMessageId: userMessage?.id,
      agentMessageId: agentMessage?.id,
    });
    expect(runtimeCall?.[4]).toBe(agentMessage?.id);
  });

  it("retryMessage reuses original userMessageId and agentMessageId", async () => {
    await useChatStore
      .getState()
      .sendMessage("conv-2", "agent-1", "retry target", "personal");

    const initialMessages = getConversationMessages("conv-2");
    const initialUserMessage = initialMessages.find(
      (message) => message.role === "user",
    );
    const initialAgentMessage = initialMessages.find(
      (message) => message.role === "agent",
    );

    expect(initialUserMessage).toBeDefined();
    expect(initialAgentMessage).toBeDefined();

    mockedExecuteChatRuntime.mockClear();

    await useChatStore.getState().retryMessage("conv-2", "agent-1", "personal");

    const messagesAfterRetry = getConversationMessages("conv-2");
    expect(messagesAfterRetry).toHaveLength(2);

    const userMessageAfterRetry = messagesAfterRetry.find(
      (message) => message.role === "user",
    );
    const agentMessageAfterRetry = messagesAfterRetry.find(
      (message) => message.role === "agent",
    );

    expect(userMessageAfterRetry?.id).toBe(initialUserMessage?.id);
    expect(agentMessageAfterRetry?.id).toBe(initialAgentMessage?.id);
    expect(agentMessageAfterRetry?.status).toBe("streaming");
    expect(agentMessageAfterRetry?.content).toBe("");
    expect(agentMessageAfterRetry?.blocks).toEqual([]);

    const session = useChatStore.getState().sessions["conv-2"];
    expect(session?.lastUserMessageId).toBe(initialUserMessage?.id);
    expect(session?.lastAgentMessageId).toBe(initialAgentMessage?.id);

    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const runtimeCall = mockedExecuteChatRuntime.mock.calls[0];
    expect(runtimeCall?.[0]).toBe("conv-2");
    expect(runtimeCall?.[1]).toBe("agent-1");
    expect(runtimeCall?.[2]).toBe("personal");
    expect(runtimeCall?.[3]).toMatchObject({
      query: "retry target",
      conversationId: "conv-2",
      userMessageId: initialUserMessage?.id,
      agentMessageId: initialAgentMessage?.id,
    });
    expect(runtimeCall?.[4]).toBe(initialAgentMessage?.id);
  });

  it("injects interrupt extension when sending during active stream", async () => {
    useChatStore.getState().ensureSession("conv-3", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-3": {
          ...state.sessions["conv-3"],
          streamState: "streaming",
        },
      },
    }));

    await useChatStore
      .getState()
      .sendMessage("conv-3", "agent-1", "interrupt this stream", "personal");

    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const runtimeCall = mockedExecuteChatRuntime.mock.calls[0];
    expect(runtimeCall?.[3]).toMatchObject({
      metadata: {
        extensions: {
          interrupt: true,
        },
      },
    });
  });

  it("cancelMessage marks streaming session as idle immediately", () => {
    useChatStore.getState().ensureSession("conv-4", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-4": {
          ...state.sessions["conv-4"],
          streamState: "streaming",
          lastStreamError: "temporary error",
          pendingInterrupt: {
            requestId: "req-1",
            type: "permission",
            details: {
              permission: "tool.exec",
              patterns: ["*"],
            },
          },
        },
      },
    }));

    useChatStore.getState().cancelMessage("conv-4");

    const session = useChatStore.getState().sessions["conv-4"];
    expect(session?.streamState).toBe("idle");
    expect(session?.lastStreamError).toBeNull();
    expect(session?.pendingInterrupt).toBeNull();
    expect(chatConnectionService.cancelSession).toHaveBeenCalledWith("conv-4");
  });
});
