import {
  addConversationMessage,
  clearAllConversationMessages,
  createAgentSession,
  createDeferred,
  executeChatRuntime,
  flushPromises,
  getConversationMessages,
  invokeAgent,
  mockedChatConnectionService,
  mockedListSessionMessagesPage,
  queryClient,
} from "./chatRuntime.test.support";
import type {
  ChatRuntimeSetState,
  ChatRuntimeState,
  SessionMessageItem,
} from "./chatRuntime.test.support";

const normalizeRuntimeStateToken = (state: string) => {
  const normalized = state.trim().toLowerCase().replace(/_/g, "-");
  return normalized.startsWith("task-state-")
    ? normalized.slice("task-state-".length)
    : normalized;
};

const buildStatusUpdate = ({
  state,
  messageId,
  completionPhase,
}: {
  state: string;
  messageId?: string;
  completionPhase?: string;
}) => ({
  statusUpdate: {
    status: { state },
    metadata: {
      shared: {
        stream: {
          ...(messageId ? { messageId } : {}),
          ...(completionPhase ? { completionPhase } : {}),
        },
      },
    },
  },
  version: "v1",
  runtimeStatus: {
    state: normalizeRuntimeStateToken(state),
    isFinal:
      state === "TASK_STATE_COMPLETED" ||
      state === "TASK_STATE_FAILED" ||
      state === "TASK_STATE_INPUT_REQUIRED",
    ...(completionPhase ? { completionPhase } : {}),
    ...(messageId ? { messageId } : {}),
  },
});

const buildArtifactUpdate = ({
  agentMessageId,
  text,
  eventId,
  seq,
  source = "assistant_text",
}: {
  agentMessageId: string;
  text: string;
  eventId: string;
  seq: number;
  source?: string;
}) => ({
  artifactUpdate: {
    op: "append",
    artifact: {
      artifactId: `${agentMessageId}:stream:1`,
      parts: [{ text }],
      metadata: {
        shared: {
          stream: {
            blockType: "text",
            source,
            messageId: agentMessageId,
            eventId,
            seq,
          },
        },
      },
    },
  },
  version: "v1",
  streamBlock: {
    eventId,
    eventIdSource: "upstream",
    messageIdSource: "upstream",
    seq,
    taskId: agentMessageId,
    artifactId: `${agentMessageId}:stream:1`,
    blockId: `${agentMessageId}:primary_text`,
    laneId: "primary_text",
    blockType: "text",
    op: "append",
    source,
    messageId: agentMessageId,
    role: "agent",
    delta: text,
    append: true,
    done: false,
  },
});

const buildRawCompatArtifactUpdate = ({
  taskId,
  text,
  eventId,
  seq,
  append = true,
  lastChunk = false,
}: {
  taskId: string;
  text: string;
  eventId: string;
  seq: number;
  append?: boolean;
  lastChunk?: boolean;
}) => ({
  artifactUpdate: {
    taskId,
    contextId: "ctx-1",
    append,
    lastChunk,
    artifact: {
      artifactId: `${taskId}:stream:text`,
      parts: [{ text }],
    },
    metadata: {
      shared: {
        stream: {
          eventId,
          seq,
        },
      },
    },
  },
  version: "v1",
  streamBlock: {
    eventId,
    eventIdSource: "upstream",
    messageIdSource: "task_fallback",
    seq,
    taskId,
    artifactId: `${taskId}:stream:text`,
    blockId: `task:${taskId}:primary_text`,
    laneId: "primary_text",
    blockType: "text",
    op: append ? "append" : "replace",
    messageId: `task:${taskId}`,
    role: "agent",
    delta: text,
    append,
    done: lastChunk,
  },
});

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
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_WORKING" }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
            messageId: agentMessageId,
            completionPhase: "persisted",
          }),
        );
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

    await flushPromises();

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

  it("renders raw A2A artifact text chunks without rekeying the placeholder message", async () => {
    const conversationId = "conv-raw-artifact-1";
    const agentId = "agent-raw-artifact-1";
    const userMessageId = "user-raw-artifact-1";
    const agentMessageId = "agent-raw-artifact-1";
    const taskId = "task-raw-artifact-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T05:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T05:10:01.000Z",
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

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_WORKING" }),
        );
        params.callbacks.onData(
          buildRawCompatArtifactUpdate({
            taskId,
            text: "Code",
            eventId: "stream:4",
            seq: 4,
          }),
        );
        params.callbacks.onData(
          buildRawCompatArtifactUpdate({
            taskId,
            text: "，你",
            eventId: "stream:5",
            seq: 5,
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
            completionPhase: "persisted",
          }),
        );
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

    await flushPromises();

    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
    expect(state.sessions[conversationId]?.lastAgentMessageId).toBe(
      agentMessageId,
    );
    expect(state.sessions[conversationId]?.streamState).toBe("idle");

    const messages = getConversationMessages(conversationId);
    expect(messages.find((message) => message.id === `task:${taskId}`)).toBe(
      undefined,
    );

    const agentMessage = messages.find(
      (message) => message.id === agentMessageId,
    );
    expect(agentMessage?.status).toBe("done");
    expect(agentMessage?.content).toBe("Code，你");
    expect(agentMessage?.blocks?.map((block) => block.type)).toEqual(["text"]);
  });

  it("marks the stream recoverable when terminal status is not followed by a persisted completion ack", async () => {
    const conversationId = "conv-terminal-status-gate-1";
    const agentId = "agent-terminal-status-gate-1";
    const userMessageId = "user-terminal-status-gate-1";
    const agentMessageId = "agent-terminal-status-gate-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-23T10:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-23T10:00:01.000Z",
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

    const transportDone = createDeferred<boolean>();
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            text: "Hello after terminal status.",
            eventId: `${agentMessageId}:1`,
            seq: 1,
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_COMPLETED" }),
        );
        await transportDone.promise;
        return true;
      },
    );

    const runtimePromise = executeChatRuntime(
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

    await flushPromises();

    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
    expect(state.sessions[conversationId]?.streamState).toBe("streaming");
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      )?.status,
    ).toBe("streaming");

    transportDone.resolve(true);
    await runtimePromise;

    expect(state.sessions[conversationId]?.streamState).toBe("recoverable");
    expect(state.sessions[conversationId]?.lastStreamError).toBe(
      "Streaming finished without a persisted completion acknowledgement.",
    );
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      ),
    ).toMatchObject({
      status: "interrupted",
      content: "Hello after terminal status.",
    });
  });

  it("finalizes immediately when an explicit persisted completion ack arrives", async () => {
    const conversationId = "conv-stream-error-1";
    const agentId = "agent-stream-error-1";
    const userMessageId = "user-stream-error-1";
    const agentMessageId = "agent-stream-error-1";

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

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            text: "Persisted ack response.",
            eventId: `${agentMessageId}:1`,
            seq: 1,
          }),
        );
        const shouldClose = params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
            messageId: agentMessageId,
            completionPhase: "persisted",
          }),
        );
        expect(shouldClose).toBe(true);
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

    expect(state.sessions[conversationId]?.streamState).toBe("idle");
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      ),
    ).toMatchObject({
      status: "done",
      content: "Persisted ack response.",
    });
  });

  it("does not treat stream_end as a successful completion without persisted ack", async () => {
    const conversationId = "conv-stream-end-without-ack-1";
    const agentId = "agent-stream-end-without-ack-1";
    const userMessageId = "user-stream-end-without-ack-1";
    const agentMessageId = "agent-stream-end-without-ack-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-23T10:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-23T10:10:01.000Z",
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

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            text: "Hello before stream end.",
            eventId: `${agentMessageId}:1`,
            seq: 1,
          }),
        );
        const shouldClose = params.callbacks.onData({
          event: "stream_end",
          data: {},
        });
        expect(shouldClose).toBe(false);
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

    expect(state.sessions[conversationId]?.streamState).toBe("recoverable");
    expect(state.sessions[conversationId]?.lastStreamError).toBe(
      "Streaming transport ended before a persisted completion acknowledgement was received.",
    );
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      ),
    ).toMatchObject({
      status: "interrupted",
      content: "Hello before stream end.",
    });
  });

  it("ignores empty stream envelopes and falls back to JSON when no stream event was observed", async () => {
    const conversationId = "conv-empty-stream-envelope-1";
    const agentId = "agent-empty-stream-envelope-1";
    const userMessageId = "user-empty-stream-envelope-1";
    const agentMessageId = "agent-empty-stream-envelope-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-23T10:20:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-23T10:20:01.000Z",
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

    invokeAgent.mockResolvedValueOnce({
      success: true,
      content: "JSON fallback response.",
    });

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({ version: "v1" });
        return false;
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

    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
    expect(invokeAgent).toHaveBeenCalledWith(
      agentId,
      expect.objectContaining({
        conversationId,
        userMessageId,
        agentMessageId,
      }),
    );
    expect(state.sessions[conversationId]?.streamState).toBe("idle");
    expect(state.sessions[conversationId]?.lastStreamError).toBeNull();
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      ),
    ).toMatchObject({
      status: "done",
      content: "JSON fallback response.",
    });
  });

  it("stores structured stream errors from websocket error events", async () => {
    const conversationId = "conv-stream-error-1";
    const agentId = "agent-stream-error-1";
    const userMessageId = "user-stream-error-1";
    const agentMessageId = "agent-stream-error-1";

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

    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData({
          event: "error",
          data: {
            message: "Upstream streaming failed",
            error_code: "invalid_params",
            source: "upstream_a2a",
            jsonrpc_code: -32602,
            missing_params: [
              { name: "project_id", required: true },
              { name: "channel_id", required: true },
            ],
            upstream_error: {
              message: "project_id/channel_id required",
            },
          },
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

    const agentMessage = getConversationMessages(conversationId).find(
      (message) => message.id === agentMessageId,
    );

    expect(state.sessions[conversationId]?.streamState).toBe("error");
    expect(state.sessions[conversationId]?.lastStreamError).toBe(
      "Missing required upstream parameters: project_id, channel_id",
    );
    expect(agentMessage).toMatchObject({
      status: "error",
      errorCode: "invalid_params",
      errorMessage:
        "Missing required upstream parameters: project_id, channel_id",
      errorSource: "upstream_a2a",
      jsonrpcCode: -32602,
      missingParams: [
        { name: "project_id", required: true },
        { name: "channel_id", required: true },
      ],
      upstreamError: {
        message: "project_id/channel_id required",
      },
    });
  });

  it("keeps rendered chunks but marks the stream recoverable when persisted completion ack is missing", async () => {
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
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_WORKING" }),
        );
        params.callbacks.onData({
          artifactUpdate: {
            op: "append",
            taskId: "task-compat-1",
            artifact: {
              artifactId: "stream-compat-1",
              parts: [{ text: "Hello from stream" }],
              metadata: {
                shared: {
                  stream: {
                    blockType: "text",
                    source: "assistant_text",
                    messageId: agentMessageId,
                    eventId: `${agentMessageId}:1`,
                    seq: 1,
                  },
                },
              },
            },
          },
          version: "v1",
          streamBlock: {
            eventId: `${agentMessageId}:1`,
            eventIdSource: "upstream",
            messageIdSource: "upstream",
            seq: 1,
            taskId: "task-compat-1",
            artifactId: "stream-compat-1",
            blockId: `${agentMessageId}:primary_text`,
            laneId: "primary_text",
            blockType: "text",
            op: "append",
            source: "assistant_text",
            messageId: agentMessageId,
            role: "agent",
            delta: "Hello from stream",
            append: true,
            done: false,
          },
        });
        await new Promise((resolve) => setTimeout(resolve, 30));
        renderedDuringStream = getConversationMessages(conversationId).some(
          (message) =>
            message.role === "agent" &&
            message.status === "streaming" &&
            message.content.includes("Hello from stream"),
        );
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_COMPLETED" }),
        );
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

    expect(state.sessions[conversationId]?.streamState).toBe("recoverable");
    expect(state.sessions[conversationId]?.lastStreamError).toBe(
      "Streaming finished without a persisted completion acknowledgement.",
    );

    const messages = getConversationMessages(conversationId);
    const streamedAgentMessage = messages.find(
      (message) =>
        message.role === "agent" &&
        message.content.includes("Hello from stream"),
    );
    expect(streamedAgentMessage?.status).toBe("interrupted");
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
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_WORKING" }),
        );
        params.callbacks.onData({
          artifactUpdate: {
            op: "replace",
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
                    blockType: "tool_call",
                    source: "tool_part_update",
                    messageId: agentMessageId,
                    eventId: `${agentMessageId}:1`,
                    seq: 1,
                  },
                },
              },
            },
          },
          version: "v1",
          streamBlock: {
            eventId: `${agentMessageId}:1`,
            eventIdSource: "upstream",
            messageIdSource: "upstream",
            seq: 1,
            taskId: agentMessageId,
            artifactId: `${agentMessageId}:stream`,
            blockId: `${agentMessageId}:tool_call`,
            laneId: "tool_call",
            blockType: "tool_call",
            op: "replace",
            source: "tool_part_update",
            messageId: agentMessageId,
            role: "agent",
            delta: JSON.stringify({
              call_id: "call-1",
              tool: "bash",
              status: "running",
              input: { command: "pwd" },
            }),
            append: false,
            done: false,
            toolCall: {
              name: "bash",
              status: "running",
              callId: "call-1",
              arguments: { command: "pwd" },
              result: null,
              error: null,
            },
          },
        });

        const agentMessage = getConversationMessages(conversationId).find(
          (message) => message.id === agentMessageId,
        );
        renderedDuringStream =
          agentMessage?.status === "streaming" &&
          (agentMessage.blocks?.length ?? 0) > 0 &&
          agentMessage?.blocks?.[0]?.type === "tool_call" &&
          agentMessage?.blocks?.[0]?.toolCall?.name === "bash" &&
          agentMessage?.blocks?.[0]?.toolCall?.status === "running";

        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
            messageId: agentMessageId,
            completionPhase: "persisted",
          }),
        );
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
        params.callbacks.onData(
          buildStatusUpdate({ state: "TASK_STATE_WORKING" }),
        );
        params.callbacks.onData({
          artifactUpdate: {
            op: "replace",
            artifact: {
              artifactId: `${agentMessageId}:stream`,
              parts: [{ text: "Reasoning in progress" }],
              metadata: {
                shared: {
                  stream: {
                    blockType: "reasoning",
                    source: "reasoning_part_update",
                    messageId: agentMessageId,
                    eventId: `${agentMessageId}:1`,
                    seq: 1,
                  },
                },
              },
            },
          },
          version: "v1",
          streamBlock: {
            eventId: `${agentMessageId}:1`,
            eventIdSource: "upstream",
            messageIdSource: "upstream",
            seq: 1,
            taskId: agentMessageId,
            artifactId: `${agentMessageId}:stream`,
            blockId: `${agentMessageId}:reasoning`,
            laneId: "reasoning",
            blockType: "reasoning",
            op: "replace",
            source: "reasoning_part_update",
            messageId: agentMessageId,
            role: "agent",
            delta: "Reasoning in progress",
            append: false,
            done: false,
          },
        });

        const agentMessage = getConversationMessages(conversationId).find(
          (message) => message.id === agentMessageId,
        );
        renderedDuringStream =
          agentMessage?.status === "streaming" &&
          (agentMessage.blocks?.length ?? 0) > 0 &&
          agentMessage?.blocks?.[0]?.type === "reasoning";

        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
            messageId: agentMessageId,
            completionPhase: "persisted",
          }),
        );
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
});
