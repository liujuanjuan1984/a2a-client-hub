import { createAgentSession } from "@/lib/chat-utils";
import { generateId } from "@/lib/id";
import { chatConnectionService } from "@/services/chatConnectionService";
import { useChatStore } from "@/store/chat";
import { executeChatRuntime } from "@/store/chatRuntime";
import { useMessageStore } from "@/store/messages";

jest.mock("@/store/chatRuntime", () => ({
  executeChatRuntime: jest.fn(),
}));

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    cancelSession: jest.fn(),
    clearAll: jest.fn(),
    getPreferredTransport: jest.fn(() => "sse"),
  },
}));

jest.mock("@/store/messages", () => ({
  useMessageStore: {
    getState: jest.fn(),
  },
}));

jest.mock("@/lib/id", () => ({
  generateId: jest.fn(),
  generateUuid: jest.fn(() => "generated-conversation-id"),
}));

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => undefined,
    removeItem: () => undefined,
  }),
}));

type TestMessageState = {
  messages: Record<string, Record<string, unknown>[]>;
  addMessage: jest.Mock;
  updateMessage: jest.Mock;
  removeMessages: jest.Mock;
};

const mockedGenerateId = generateId as jest.MockedFunction<typeof generateId>;
const mockedExecuteChatRuntime = executeChatRuntime as jest.MockedFunction<
  typeof executeChatRuntime
>;
const mockedMessageStoreGetState = useMessageStore.getState as jest.Mock;

describe("useChatStore.sendMessage interrupt semantics", () => {
  const conversationId = "conv-1";
  const agentId = "agent-1";
  let messageState: TestMessageState;

  beforeEach(() => {
    jest.clearAllMocks();
    messageState = {
      messages: {},
      addMessage: jest.fn((cid: string, message: Record<string, unknown>) => {
        const current = messageState.messages[cid] ?? [];
        messageState.messages[cid] = [...current, message];
      }),
      updateMessage: jest.fn(
        (cid: string, messageId: string, payload: Record<string, unknown>) => {
          const current = messageState.messages[cid] ?? [];
          messageState.messages[cid] = current.map((message) =>
            message.id === messageId ? { ...message, ...payload } : message,
          );
        },
      ),
      removeMessages: jest.fn(),
    };
    mockedMessageStoreGetState.mockImplementation(() => messageState);
    mockedExecuteChatRuntime.mockResolvedValue(undefined);
    useChatStore.getState().clearAll();
  });

  it("does not inject interrupt metadata for a fresh non-streaming send", async () => {
    mockedGenerateId
      .mockReturnValueOnce("user-1")
      .mockReturnValueOnce("agent-1");

    useChatStore.getState().ensureSession(conversationId, agentId);

    await useChatStore
      .getState()
      .sendMessage(conversationId, agentId, "hello", "shared");

    expect(chatConnectionService.cancelSession).toHaveBeenCalledWith(
      conversationId,
    );
    expect(messageState.updateMessage).not.toHaveBeenCalled();
    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const payload = mockedExecuteChatRuntime.mock.calls[0]?.[3];
    expect(payload?.metadata).toBeUndefined();
  });

  it("injects interrupt metadata and settles the previous streaming agent message", async () => {
    mockedGenerateId
      .mockReturnValueOnce("user-2")
      .mockReturnValueOnce("agent-2");

    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        [conversationId]: {
          ...createAgentSession(agentId),
          streamState: "streaming",
          metadata: { locale: "zh-CN" },
        },
      },
    }));
    messageState.messages[conversationId] = [
      {
        id: "agent-old",
        role: "agent",
        content: "old",
        createdAt: "2026-02-25T00:00:00.000Z",
        status: "streaming",
      },
    ];

    await useChatStore
      .getState()
      .sendMessage(conversationId, agentId, "next", "shared");

    expect(messageState.updateMessage).toHaveBeenCalledWith(
      conversationId,
      "agent-old",
      { status: "done" },
    );
    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const payload = mockedExecuteChatRuntime.mock.calls[0]?.[3];
    expect(payload?.metadata).toMatchObject({
      locale: "zh-CN",
      extensions: { interrupt: true },
    });
  });
});
