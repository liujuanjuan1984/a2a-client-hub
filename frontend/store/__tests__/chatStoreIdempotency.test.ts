import {
  addConversationMessage,
  getConversationMessages,
} from "@/lib/chatHistoryCache";
import { useChatStore } from "@/store/chat";
import { executeChatRuntime } from "@/store/chatRuntime";

jest.mock("@/lib/storage/mmkv", () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/services/chatConnectionService", () => ({
  chatConnectionService: {
    cancelSession: jest.fn(async () => {}),
    hasActiveConnection: jest.fn(() => false),
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
    hasActiveConnection: jest.Mock;
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

  it("sets explicit preempt session control when sending during active stream", async () => {
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
      sessionControl: {
        intent: "preempt",
      },
    });
  });

  it("sends neutral session binding intent and leaves metadata shape adaptation to backend", async () => {
    useChatStore.getState().ensureSession("conv-cap", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-cap": {
          ...state.sessions["conv-cap"],
          externalSessionRef: {
            provider: "OpenCode",
            externalSessionId: "ses-upstream-cap",
          },
        },
      },
    }));

    await useChatStore
      .getState()
      .sendMessage("conv-cap", "agent-1", "hello world", "personal");

    const runtimeCall = mockedExecuteChatRuntime.mock.calls[0];
    expect(runtimeCall?.[3]).toMatchObject({
      sessionBinding: {
        provider: "opencode",
        externalSessionId: "ses-upstream-cap",
      },
    });
    expect(runtimeCall?.[3]?.metadata?.provider).toBeUndefined();
    expect(runtimeCall?.[3]?.metadata?.externalSessionId).toBeUndefined();
    const sharedMetadata = runtimeCall?.[3]?.metadata?.shared as
      | Record<string, unknown>
      | undefined;
    expect(sharedMetadata?.session).toBeUndefined();
  });

  it("cancelMessage marks streaming session as idle immediately", () => {
    useChatStore.getState().ensureSession("conv-4", "agent-1");
    const streamingAgentMessageId = "agent-stream-1";
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-4": {
          ...state.sessions["conv-4"],
          lastAgentMessageId: streamingAgentMessageId,
        },
      },
    }));
    addConversationMessage("conv-4", {
      id: streamingAgentMessageId,
      role: "agent",
      content: "",
      createdAt: "2026-02-24T00:00:00.000Z",
      status: "streaming",
      blocks: [],
    });
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
            phase: "asked",
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
    expect(
      getConversationMessages("conv-4").find(
        (message) => message.id === streamingAgentMessageId,
      )?.status,
    ).toBe("interrupted");
    expect(chatConnectionService.cancelSession).toHaveBeenCalledWith("conv-4");
  });

  it("cancelMessage skips server cancel when session is idle and no active connection", () => {
    useChatStore.getState().ensureSession("conv-5", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-5": {
          ...state.sessions["conv-5"],
          streamState: "idle",
        },
      },
    }));

    useChatStore.getState().cancelMessage("conv-5");

    expect(chatConnectionService.cancelSession).not.toHaveBeenCalled();
  });

  it("cancelMessage requests server cancel when idle session has active connection", () => {
    useChatStore.getState().ensureSession("conv-6", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-6": {
          ...state.sessions["conv-6"],
          streamState: "idle",
        },
      },
    }));
    chatConnectionService.hasActiveConnection.mockReturnValueOnce(true);

    useChatStore.getState().cancelMessage("conv-6");

    expect(chatConnectionService.cancelSession).toHaveBeenCalledWith("conv-6");
  });

  it("cancelMessage coalesces duplicate server cancel requests in short window", () => {
    useChatStore.getState().ensureSession("conv-7", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-7": {
          ...state.sessions["conv-7"],
          streamState: "recoverable",
        },
      },
    }));

    useChatStore.getState().cancelMessage("conv-7");
    useChatStore.getState().cancelMessage("conv-7");

    expect(chatConnectionService.cancelSession).toHaveBeenCalledTimes(1);
  });

  it("resumeMessage reuses the existing ids and forwards resumeFromSequence", async () => {
    const userMessageId = "user-resume-1";
    const agentMessageId = "agent-resume-1";

    useChatStore.getState().ensureSession("conv-8", "agent-1");
    addConversationMessage("conv-8", {
      id: userMessageId,
      role: "user",
      content: "resume target",
      createdAt: "2026-03-21T12:00:00.000Z",
      status: "done",
    });
    addConversationMessage("conv-8", {
      id: agentMessageId,
      role: "agent",
      content: "partial",
      createdAt: "2026-03-21T12:00:01.000Z",
      status: "interrupted",
      blocks: [],
    });
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-8": {
          ...state.sessions["conv-8"],
          streamState: "recoverable",
          lastUserMessageId: userMessageId,
          lastAgentMessageId: agentMessageId,
          lastReceivedSequence: 7,
        },
      },
    }));

    await useChatStore.getState().resumeMessage("conv-8");

    expect(mockedExecuteChatRuntime).toHaveBeenCalledTimes(1);
    const runtimeCall = mockedExecuteChatRuntime.mock.calls[0];
    expect(runtimeCall?.[0]).toBe("conv-8");
    expect(runtimeCall?.[1]).toBe("agent-1");
    expect(runtimeCall?.[3]).toMatchObject({
      query: "resume target",
      conversationId: "conv-8",
      userMessageId,
      agentMessageId,
      resumeFromSequence: 7,
    });
    expect(runtimeCall?.[4]).toBe(agentMessageId);
    expect(chatConnectionService.cancelSession).not.toHaveBeenCalled();
  });

  it("replaceRecoveredInterrupts reconciles recovery items without dropping live stream items", () => {
    useChatStore.getState().ensureSession("conv-recovery", "agent-1");
    useChatStore.setState((state) => ({
      sessions: {
        ...state.sessions,
        "conv-recovery": {
          ...state.sessions["conv-recovery"],
          pendingInterrupts: [
            {
              requestId: "stream-1",
              sessionId: "sess-1",
              type: "permission",
              phase: "asked",
              source: "stream",
              details: {
                permission: "tool.exec",
                patterns: ["src/**"],
              },
            },
            {
              requestId: "recovery-stale-1",
              sessionId: "sess-1",
              type: "question",
              phase: "asked",
              source: "recovery",
              details: {
                questions: [],
              },
            },
          ],
          pendingInterrupt: {
            requestId: "stream-1",
            sessionId: "sess-1",
            type: "permission",
            phase: "asked",
            source: "stream",
            details: {
              permission: "tool.exec",
              patterns: ["src/**"],
            },
          },
        },
      },
    }));

    useChatStore.getState().replaceRecoveredInterrupts(
      "conv-recovery",
      [
        {
          requestId: "stream-1",
          sessionId: "sess-1",
          type: "permission",
          phase: "asked",
          source: "recovery",
          details: {
            permission: "tool.exec",
            patterns: ["src/**"],
          },
        },
        {
          requestId: "recovery-fresh-1",
          sessionId: "sess-1",
          type: "question",
          phase: "asked",
          source: "recovery",
          details: {
            questions: [],
          },
        },
      ],
      { sessionId: "sess-1" },
    );

    const session = useChatStore.getState().sessions["conv-recovery"];
    expect(session?.pendingInterrupts).toEqual([
      {
        requestId: "stream-1",
        sessionId: "sess-1",
        type: "permission",
        phase: "asked",
        source: "stream",
        details: {
          permission: "tool.exec",
          patterns: ["src/**"],
        },
      },
      {
        requestId: "recovery-fresh-1",
        sessionId: "sess-1",
        type: "question",
        phase: "asked",
        source: "recovery",
        details: {
          questions: [],
        },
      },
    ]);
    expect(session?.pendingInterrupt?.requestId).toBe("stream-1");
  });
});
