import {
  ApiRequestError,
  addConversationMessage,
  clearAllConversationMessages,
  createAgentSession,
  executeChatRuntime,
  getConversationMessages,
  invokeAgent,
  invokeHubAgent,
  queryClient,
} from "./chatRuntime.test.support";
import type {
  ChatRuntimeSetState,
  ChatRuntimeState,
} from "./chatRuntime.test.support";

describe("executeChatRuntime failure handling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    queryClient.clear();
    clearAllConversationMessages();
  });

  it("marks JSON fallback business failures as message errors with structured code", async () => {
    const conversationId = "conv-json-error-1";
    const agentId = "agent-json-error-1";
    const userMessageId = "user-json-error-1";
    const agentMessageId = "agent-json-error-1";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T09:00:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T09:00:01.000Z",
      status: "streaming",
    });

    invokeAgent.mockResolvedValueOnce({
      success: false,
      error: "Upstream agent is unavailable.",
      error_code: "agent_unavailable",
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
      "Upstream agent is unavailable.",
    );
    expect(agentMessage).toMatchObject({
      status: "error",
      content: "",
      errorCode: "agent_unavailable",
      errorMessage: "Upstream agent is unavailable.",
    });
  });

  it("surfaces structured JSON fallback errors with missing params", async () => {
    const conversationId = "conv-json-error-structured";
    const agentId = "agent-json-error-structured";
    const userMessageId = "user-json-error-structured";
    const agentMessageId = "agent-json-error-structured";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T09:05:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T09:05:01.000Z",
      status: "streaming",
    });

    invokeAgent.mockResolvedValueOnce({
      success: false,
      error: "Upstream streaming failed",
      error_code: "invalid_params",
      source: "upstream_a2a",
      jsonrpc_code: -32602,
      missing_params: [{ name: "project_id", required: true }],
      upstream_error: {
        message: "project_id required",
      },
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
      "Missing required upstream parameters: project_id",
    );
    expect(agentMessage).toMatchObject({
      status: "error",
      errorCode: "invalid_params",
      errorMessage: "Missing required upstream parameters: project_id",
      errorSource: "upstream_a2a",
      jsonrpcCode: -32602,
      missingParams: [{ name: "project_id", required: true }],
      upstreamError: {
        message: "project_id required",
      },
    });
  });

  it("marks JSON fallback request exceptions as message errors with API error code", async () => {
    const conversationId = "conv-json-error-2";
    const agentId = "agent-json-error-2";
    const userMessageId = "user-json-error-2";
    const agentMessageId = "agent-json-error-2";

    addConversationMessage(conversationId, {
      id: userMessageId,
      role: "user",
      content: "hello",
      createdAt: "2026-03-12T09:10:00.000Z",
      status: "done",
    });
    addConversationMessage(conversationId, {
      id: agentMessageId,
      role: "agent",
      content: "",
      blocks: [],
      createdAt: "2026-03-12T09:10:01.000Z",
      status: "streaming",
    });

    const apiError = new ApiRequestError("Request failed [timeout]", 504, {
      errorCode: "timeout",
    });
    invokeHubAgent.mockRejectedValueOnce(apiError);

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

    await executeChatRuntime(
      conversationId,
      agentId,
      "shared",
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
    expect(agentMessage).toMatchObject({
      status: "error",
      content: "",
      errorCode: "timeout",
      errorMessage: "Request failed [timeout]",
    });
  });
});
