jest.mock("react-native", () => ({
  Platform: {
    OS: "web",
  },
}));

jest.mock("@/lib/config", () => ({
  ENV: {
    apiBaseUrl: "http://localhost:8000",
  },
}));

jest.mock("@/lib/api/client", () => ({
  ApiRequestError: class MockApiRequestError extends Error {
    status: number;
    errorCode: string | null;

    constructor(
      message: string,
      status: number,
      errorCode: string | null = null,
    ) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      this.errorCode = errorCode;
    }
  },
  isAuthFailureError: jest.fn(() => false),
  isAuthorizationFailureError: jest.fn(() => false),
}));

jest.mock("@/lib/api/sse", () => ({
  fetchSSE: jest.fn(),
}));

const { fetchSSE } = require("@/lib/api/sse") as {
  fetchSSE: jest.Mock;
};
const { trySseTransport } = require("@/services/chatTransportSse") as {
  trySseTransport: (params: Record<string, unknown>) => Promise<boolean>;
};

describe("chatTransportSse", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("passes idle timeout config and forwards structured stream errors", async () => {
    fetchSSE.mockImplementationOnce(async (_url, handlers, options) => {
      expect(options.idleTimeoutMs).toBe(45_000);
      expect(options.reconnect).toMatchObject({
        retries: 2,
        initialDelayMs: 800,
        maxDelayMs: 8_000,
        jitterMs: 250,
        onlyIfNoData: true,
      });

      handlers.onData?.({ kind: "chunk" });
      handlers.onError?.(
        Object.assign(new Error("Upstream streaming failed"), {
          errorCode: "agent_unavailable",
        }),
      );
    });

    const callbacks = {
      onData: jest.fn(),
      onDone: jest.fn(),
      onStreamError: jest.fn(),
    };
    const controllers = new Map<string, AbortController>();
    const health = {
      recordSseSuccess: jest.fn(),
      recordSseFailure: jest.fn(),
    };

    const result = await trySseTransport({
      conversationId: "conv-sse-1",
      agentId: "agent-1",
      source: "personal",
      payload: { query: "hello" },
      callbacks,
      controllers,
      health,
    });

    expect(result).toBe(true);
    expect(controllers.size).toBe(0);
    expect(health.recordSseSuccess).toHaveBeenCalledTimes(1);
    expect(health.recordSseFailure).not.toHaveBeenCalled();
    expect(callbacks.onStreamError).toHaveBeenCalledWith(
      "Upstream streaming failed",
      "agent_unavailable",
    );
  });

  it("records failures before the first SSE payload", async () => {
    const streamError = new Error("Initial stream connect failed");
    fetchSSE.mockRejectedValueOnce(streamError);

    const callbacks = {
      onData: jest.fn(),
      onDone: jest.fn(),
      onStreamError: jest.fn(),
    };
    const controllers = new Map<string, AbortController>();
    const health = {
      recordSseSuccess: jest.fn(),
      recordSseFailure: jest.fn(),
    };

    const result = await trySseTransport({
      conversationId: "conv-sse-2",
      agentId: "agent-1",
      source: "personal",
      payload: { query: "hello" },
      callbacks,
      controllers,
      health,
    });

    expect(result).toBe(false);
    expect(controllers.size).toBe(0);
    expect(health.recordSseFailure).toHaveBeenCalledWith(streamError);
    expect(callbacks.onStreamError).not.toHaveBeenCalled();
  });
});
