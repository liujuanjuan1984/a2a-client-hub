import {
  DEFAULT_RUNTIME_STATUS_CONTRACT,
  addConversationMessage,
  buildPendingInterruptState,
  clearAllConversationMessages,
  createAgentSession,
  executeChatRuntime,
  getConversationMessages,
  getPendingInterruptQueue,
  mockedChatConnectionService,
  mockedListSessionMessagesPage,
  queryClient,
} from "./chatRuntime.test.support";
import type {
  ChatRuntimeSetState,
  ChatRuntimeState,
  RuntimeStatusContract,
} from "./chatRuntime.test.support";

const buildStatusUpdate = ({
  state,
  seq,
  messageId,
  completionPhase,
  interrupt,
}: {
  state: string;
  seq?: number;
  messageId?: string;
  completionPhase?: string;
  interrupt?: Record<string, unknown>;
}) => ({
  statusUpdate: {
    status: { state },
    metadata: {
      shared: {
        ...(interrupt ? { interrupt } : {}),
        stream: {
          ...(seq !== undefined ? { seq } : {}),
          ...(messageId ? { messageId } : {}),
          ...(completionPhase ? { completionPhase } : {}),
        },
      },
    },
  },
});

const buildArtifactUpdate = ({
  agentMessageId,
  eventId,
  seq,
  text,
  source = "assistant_text",
}: {
  agentMessageId: string;
  eventId: string;
  seq: number;
  text: string;
  source?: string;
}) => ({
  artifactUpdate: {
    append: true,
    artifact: {
      artifactId: `${agentMessageId}:stream:${seq}`,
      parts: [{ text }],
      metadata: {
        shared: {
          stream: {
            block_type: "text",
            source,
            messageId: agentMessageId,
            eventId,
            seq,
          },
        },
      },
    },
  },
});

describe("executeChatRuntime empty-content recovery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    queryClient.clear();
    clearAllConversationMessages();
  });

  it("inserts interrupt_event blocks inline during stream status updates", async () => {
    const conversationId = "conv-stream-interrupt-block-1";
    const agentId = "agent-interrupt-block-1";
    const userMessageId = "user-msg-interrupt-block-1";
    const agentMessageId = "agent-msg-interrupt-block-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T06:30:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T06:30:01.000Z",
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

    let interruptBlockSnapshot:
      | {
          type?: string;
          content?: string;
        }
      | undefined;
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_INPUT_REQUIRED",
            interrupt: {
              requestId: "perm-inline-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          }),
        );

        const agentMessage = getConversationMessages(conversationId).find(
          (message) => message.id === agentMessageId,
        );
        interruptBlockSnapshot = agentMessage?.blocks?.[0];

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

    expect(interruptBlockSnapshot).toMatchObject({
      type: "interrupt_event",
      content: "Agent requested permission: read.\nTargets: /repo/.env",
    });
    expect(state.sessions[conversationId]?.pendingInterrupts).toEqual([]);
    expect(state.sessions[conversationId]?.pendingInterrupt).toBeNull();
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

    let pendingAfterWorking = getPendingInterruptQueue(
      state.sessions[conversationId],
    );
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_INPUT_REQUIRED",
            interrupt: {
              requestId: "perm-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
          }),
        );
        pendingAfterWorking = getPendingInterruptQueue(
          state.sessions[conversationId],
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

    expect(pendingAfterWorking).toHaveLength(1);
    expect(pendingAfterWorking[0]).toMatchObject({
      requestId: "perm-1",
      type: "permission",
      phase: "asked",
    });
    expect(state.sessions[conversationId]?.pendingInterrupts).toEqual([]);
    expect(state.sessions[conversationId]?.pendingInterrupt).toBeNull();
    expect(state.sessions[conversationId]?.lastResolvedInterrupt).toBeNull();
  });

  it("applies capability runtime status aliases during stream parsing", async () => {
    const conversationId = "conv-interrupt-contract-1";
    const agentId = "agent-interrupt-contract-1";
    const userMessageId = "user-msg-interrupt-contract-1";
    const agentMessageId = "agent-msg-interrupt-contract-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T07:30:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T07:30:01.000Z",
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

    let pendingAfterAlias = getPendingInterruptQueue(
      state.sessions[conversationId],
    );
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildStatusUpdate({
            state: "approval_needed",
            interrupt: {
              requestId: "perm-contract-1",
              type: "permission",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          }),
        );
        pendingAfterAlias = getPendingInterruptQueue(
          state.sessions[conversationId],
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
          }),
        );
        return true;
      },
    );

    const customRuntimeStatusContract: RuntimeStatusContract = {
      ...DEFAULT_RUNTIME_STATUS_CONTRACT,
      aliases: {
        ...DEFAULT_RUNTIME_STATUS_CONTRACT.aliases,
        approval_needed: "input-required",
      },
    };

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
      { runtimeStatusContract: customRuntimeStatusContract },
    );

    expect(pendingAfterAlias).toHaveLength(1);
    expect(pendingAfterAlias[0]).toMatchObject({
      requestId: "perm-contract-1",
      type: "permission",
      phase: "asked",
    });
    expect(state.sessions[conversationId]?.runtimeStatus).toBe("completed");
  });

  it("queues multiple pending interrupts and advances by matching request id", async () => {
    const conversationId = "conv-interrupt-queue-1";
    const agentId = "agent-interrupt-queue-1";
    const userMessageId = "user-msg-interrupt-queue-1";
    const agentMessageId = "agent-msg-interrupt-queue-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T07:45:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T07:45:01.000Z",
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

    const queueSnapshots: string[][] = [];
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_INPUT_REQUIRED",
            interrupt: {
              requestId: "perm-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          }),
        );
        queueSnapshots.push(
          getPendingInterruptQueue(state.sessions[conversationId]).map(
            (interrupt) => interrupt.requestId,
          ),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_AUTH_REQUIRED",
            interrupt: {
              requestId: "perm-2",
              type: "permission",
              phase: "asked",
              details: {
                permission: "write",
                patterns: ["/repo/src/**"],
              },
            },
          }),
        );
        queueSnapshots.push(
          getPendingInterruptQueue(state.sessions[conversationId]).map(
            (interrupt) => interrupt.requestId,
          ),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
            interrupt: {
              requestId: "perm-2",
              type: "permission",
              phase: "resolved",
              resolution: "replied",
            },
          }),
        );
        queueSnapshots.push(
          getPendingInterruptQueue(state.sessions[conversationId]).map(
            (interrupt) => interrupt.requestId,
          ),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
            interrupt: {
              requestId: "perm-1",
              type: "permission",
              phase: "resolved",
              resolution: "replied",
            },
          }),
        );
        queueSnapshots.push(
          getPendingInterruptQueue(state.sessions[conversationId]).map(
            (interrupt) => interrupt.requestId,
          ),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
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

    expect(queueSnapshots).toEqual([
      ["perm-1"],
      ["perm-1", "perm-2"],
      ["perm-1"],
      [],
    ]);
    expect(state.sessions[conversationId]?.pendingInterrupts).toEqual([]);
    expect(state.sessions[conversationId]?.pendingInterrupt).toBeNull();
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
          ...buildPendingInterruptState([
            {
              requestId: "perm-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          ]),
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
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
            interrupt: {
              requestId: "q-other",
              type: "question",
              phase: "resolved",
              resolution: "rejected",
            },
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
            interrupt: {
              requestId: "perm-1",
              type: "permission",
              phase: "resolved",
              resolution: "replied",
            },
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
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

    expect(state.sessions[conversationId]?.pendingInterrupts).toEqual([]);
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

  it("renders non-contiguous chunk seq values during streaming", async () => {
    const conversationId = "conv-stream-noncontiguous-seq-1";
    const agentId = "agent-stream-noncontiguous-seq-1";
    const userMessageId = "user-msg-stream-noncontiguous-seq-1";
    const agentMessageId = "agent-msg-stream-noncontiguous-seq-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-21T09:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-21T09:10:01.000Z",
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

    let contentDuringStream = "";
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            eventId: `${agentMessageId}:1`,
            seq: 1,
            text: "Hello ",
          }),
        );
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            eventId: `${agentMessageId}:3`,
            seq: 3,
            text: "world",
          }),
        );
        await new Promise((resolve) => setTimeout(resolve, 30));
        contentDuringStream =
          getConversationMessages(conversationId).find(
            (message) => message.id === agentMessageId,
          )?.content ?? "";
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
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

    expect(contentDuringStream).toBe("Hello world");
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
  });

  it("continues rendering chunks after interrupt resolution", async () => {
    const conversationId = "conv-interrupt-resume-seq-reset-1";
    const agentId = "agent-interrupt-resume-seq-reset-1";
    const userMessageId = "user-msg-interrupt-resume-seq-reset-1";
    const agentMessageId = "agent-msg-interrupt-resume-seq-reset-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-21T08:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-21T08:10:01.000Z",
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

    let contentDuringResume = "";
    mockedChatConnectionService.tryWebSocketTransport.mockImplementationOnce(
      async (params: {
        callbacks: {
          onData: (data: Record<string, unknown>) => boolean | void;
        };
      }) => {
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            eventId: `${agentMessageId}:1`,
            seq: 1,
            text: "Before interrupt. ",
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_INPUT_REQUIRED",
            interrupt: {
              requestId: "perm-resume-1",
              type: "permission",
              phase: "asked",
              details: {
                permission: "read",
                patterns: ["/repo/.env"],
              },
            },
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_WORKING",
            interrupt: {
              requestId: "perm-resume-1",
              type: "permission",
              phase: "resolved",
              resolution: "replied",
            },
          }),
        );
        params.callbacks.onData(
          buildArtifactUpdate({
            agentMessageId,
            eventId: `${agentMessageId}:3`,
            seq: 3,
            text: "After resume.",
          }),
        );
        await new Promise((resolve) => setTimeout(resolve, 30));
        contentDuringResume =
          getConversationMessages(conversationId).find(
            (message) => message.id === agentMessageId,
          )?.content ?? "";
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_COMPLETED",
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

    expect(contentDuringResume).toContain("Before interrupt.");
    expect(contentDuringResume).toContain("After resume.");
    expect(mockedListSessionMessagesPage).not.toHaveBeenCalled();
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      )?.content,
    ).toContain("After resume.");
  });

  it("tracks status-update seq values in the resume cursor", async () => {
    const conversationId = "conv-status-seq-resume-1";
    const agentId = "agent-status-seq-resume-1";
    const userMessageId = "user-msg-status-seq-resume-1";
    const agentMessageId = "agent-msg-status-seq-resume-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-21T11:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-21T11:00:01.000Z",
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
            eventId: `${agentMessageId}:1`,
            seq: 1,
            text: "Before interrupt. ",
          }),
        );
        params.callbacks.onData(
          buildStatusUpdate({
            state: "TASK_STATE_INPUT_REQUIRED",
            seq: 2,
            interrupt: {
              requestId: "status-seq-interrupt-1",
              type: "question",
              details: {
                questions: [
                  {
                    question: "Continue?",
                    options: [{ label: "Yes", value: "yes" }],
                  },
                ],
              },
            },
          }),
        );
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

    expect(state.sessions[conversationId]?.lastReceivedSequence).toBe(2);
    expect(state.sessions[conversationId]?.streamState).toBe("recoverable");
    expect(
      getConversationMessages(conversationId).find(
        (message) => message.id === agentMessageId,
      )?.status,
    ).toBe("interrupted");
  });
});
