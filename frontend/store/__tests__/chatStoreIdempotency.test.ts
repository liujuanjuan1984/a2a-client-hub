import { useChatStore } from "@/store/chat";
import { executeChatRuntime } from "@/store/chatRuntime";
import { useMessageStore } from "@/store/messages";

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    cancelSession: jest.fn(),
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

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("chat store idempotency semantics", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useChatStore.getState().clearAll();
    useMessageStore.getState().clearAll();
  });

  it("sendMessage creates UUID message ids and forwards userMessageId", async () => {
    await useChatStore
      .getState()
      .sendMessage("conv-1", "agent-1", "hello world", "personal");

    const messages = useMessageStore.getState().messages["conv-1"] ?? [];
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

    const initialMessages = useMessageStore.getState().messages["conv-2"] ?? [];
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

    const messagesAfterRetry =
      useMessageStore.getState().messages["conv-2"] ?? [];
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
});
