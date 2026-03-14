jest.mock("@/lib/config", () => ({
  ENV: {
    apiBaseUrl: "http://localhost:8000",
  },
}));

jest.mock("@/lib/api/client", () => {
  class MockApiRequestError extends Error {
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
  }

  return {
    ApiRequestError: MockApiRequestError,
    isAuthFailureError: jest.fn(() => false),
    isAuthorizationFailureError: jest.fn(() => false),
  };
});

jest.mock("@/lib/api/sessions", () => ({
  cancelSession: jest.fn(),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  getInvokeWsTicket: jest.fn().mockResolvedValue({ token: "test-token" }),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  getHubInvokeWsTicket: jest.fn().mockResolvedValue({ token: "test-token" }),
}));

let OriginalWebSocket: any = globalThis.WebSocket;
let mockWs: any = {
  close: jest.fn(),
  send: jest.fn(),
};
(globalThis as any).WebSocket = jest.fn(() => mockWs);

afterAll(() => {
  globalThis.WebSocket = OriginalWebSocket;
});

const { ApiRequestError } = require("@/lib/api/client") as {
  ApiRequestError: new (
    message: string,
    status: number,
    errorCode?: string | null,
  ) => Error;
};
const { cancelSession: cancelSessionApi } = require("@/lib/api/sessions") as {
  cancelSession: jest.Mock;
};
const { chatConnectionService } =
  require("@/services/chatConnectionService") as {
    chatConnectionService: any;
  };

describe("chatConnectionService", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("cancelSession", () => {
    it("treats session_not_found as an idempotent no-op", async () => {
      const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
      cancelSessionApi.mockRejectedValue(
        new ApiRequestError('{"message":"session_not_found"}', 404),
      );

      const result = await chatConnectionService.cancelSession(" conv-1 ");

      expect(result).toEqual({
        conversationId: "conv-1",
        taskId: null,
        cancelled: false,
        status: "no_inflight",
      });
      expect(warnSpy).not.toHaveBeenCalled();
      warnSpy.mockRestore();
    });

    it("logs warning for non-idempotent cancellation failures", async () => {
      const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
      cancelSessionApi.mockRejectedValue(new ApiRequestError("boom", 500));

      const result = await chatConnectionService.cancelSession("conv-2");

      expect(result).toBeNull();
      expect(warnSpy).toHaveBeenCalledTimes(1);
      warnSpy.mockRestore();
    });
  });

  describe("tryWebSocketTransport edge cases", () => {
    beforeEach(() => {
      mockWs.close.mockClear();
      mockWs.send.mockClear();
      mockWs.onopen = undefined;
      mockWs.onmessage = undefined;
      mockWs.onclose = undefined;
      mockWs.onerror = undefined;
    });

    afterEach(() => {
    });

    it("handles onclose without terminal event", async () => {
      const callbacks = {
        onData: jest.fn(),
        onDone: jest.fn(),
        onStreamError: jest.fn(),
      };

      const p = chatConnectionService.tryWebSocketTransport({
        conversationId: "conv-1",
        agentId: "agent-1",
        source: "personal",
        payload: { query: "hello" },
        callbacks,
      });

      await new Promise(resolve => setTimeout(resolve, 10));
      
      mockWs.onopen();
      
      // Send some data
      mockWs.onmessage({ data: JSON.stringify({ kind: "chunk" }) });
      await new Promise(resolve => setTimeout(resolve, 10));
      
      // Simulate close before receiving terminal event
      mockWs.onclose();
      
      try {
        await p;
      } catch (e) {
        // Expected to throw
      }
      
      expect(callbacks.onStreamError).toHaveBeenCalledWith("WebSocket closed unexpectedly", "stream_closed");
    });
    
    it("handles onerror without terminal event", async () => {
      const callbacks = {
        onData: jest.fn().mockReturnValue(false), // return false means not terminal
        onDone: jest.fn(),
        onStreamError: jest.fn(),
      };

      const p = chatConnectionService.tryWebSocketTransport({
        conversationId: "conv-3",
        agentId: "agent-1",
        source: "personal",
        payload: { query: "hello" },
        callbacks,
      });

      await new Promise(resolve => setTimeout(resolve, 10));
      
      mockWs.onopen();
      mockWs.onmessage({ data: JSON.stringify({ kind: "chunk" }) });
      await new Promise(resolve => setTimeout(resolve, 10));
      
      mockWs.onerror();
      try {
        await p;
      } catch (e) {}
      
      expect(callbacks.onStreamError).toHaveBeenCalledWith("WebSocket error", "stream_error");
    });
  });
});
