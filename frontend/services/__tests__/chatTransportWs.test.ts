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
  isAuthFailureError: jest.fn(() => false),
  isAuthorizationFailureError: jest.fn(() => false),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  getInvokeWsTicket: jest.fn().mockResolvedValue({ token: "test-token" }),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  getHubInvokeWsTicket: jest.fn().mockResolvedValue({ token: "hub-token" }),
}));

type MockSocket = {
  close: jest.Mock;
  send: jest.Mock;
  __cancelled?: boolean;
  onopen?: () => void;
  onmessage?: (event: { data: unknown }) => void;
  onclose?: () => void;
  onerror?: () => void;
};

const originalWebSocket = globalThis.WebSocket;
let currentSocket: MockSocket;
const MockWebSocket = jest.fn(() => {
  currentSocket = {
    close: jest.fn(),
    send: jest.fn(),
  };
  return currentSocket;
}) as unknown as typeof WebSocket;

globalThis.WebSocket = MockWebSocket;

const flushMicrotasks = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

afterAll(() => {
  globalThis.WebSocket = originalWebSocket;
});

const { tryWebSocketTransport } = require("@/services/chatTransportWs") as {
  tryWebSocketTransport: (params: Record<string, unknown>) => Promise<boolean>;
};

describe("chatTransportWs", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
    currentSocket = undefined as unknown as MockSocket;
  });

  it("records connection failures before the first payload", async () => {
    const callbacks = {
      onData: jest.fn(),
      onDone: jest.fn(),
      onStreamError: jest.fn(),
    };
    const health = {
      recordWsSuccess: jest.fn(),
      recordWsFailure: jest.fn(),
    };
    const connections = new Map<string, MockSocket>();

    const transportPromise = tryWebSocketTransport({
      conversationId: "conv-ws-1",
      agentId: "agent-1",
      source: "personal",
      payload: { query: "hello" },
      callbacks,
      connections,
      health,
    });

    await flushMicrotasks();
    currentSocket.onopen?.();
    currentSocket.onerror?.();

    await expect(transportPromise).resolves.toBe(false);
    expect(health.recordWsFailure).toHaveBeenCalledTimes(1);
    expect(callbacks.onStreamError).not.toHaveBeenCalled();
    expect(connections.size).toBe(0);
  });

  it("forwards stream errors after receiving the first payload", async () => {
    const callbacks = {
      onData: jest.fn().mockReturnValue(false),
      onDone: jest.fn(),
      onStreamError: jest.fn(),
    };
    const health = {
      recordWsSuccess: jest.fn(),
      recordWsFailure: jest.fn(),
    };
    const connections = new Map<string, MockSocket>();

    const transportPromise = tryWebSocketTransport({
      conversationId: "conv-ws-2",
      agentId: "agent-1",
      source: "personal",
      payload: { query: "hello" },
      callbacks,
      connections,
      health,
    });

    await flushMicrotasks();
    currentSocket.onopen?.();
    currentSocket.onmessage?.({
      data: JSON.stringify({ kind: "chunk" }),
    });
    await flushMicrotasks();
    currentSocket.onerror?.();

    await expect(transportPromise).resolves.toBe(true);
    expect(currentSocket.send).toHaveBeenCalledWith(
      JSON.stringify({ query: "hello" }),
    );
    expect(health.recordWsSuccess).toHaveBeenCalledTimes(1);
    expect(health.recordWsFailure).not.toHaveBeenCalled();
    expect(callbacks.onStreamError).toHaveBeenCalledWith(
      "WebSocket error",
      "stream_error",
    );
  });

  it("treats post-data idle timeout as a recoverable stream timeout", async () => {
    jest.useFakeTimers();

    const callbacks = {
      onData: jest.fn().mockReturnValue(false),
      onDone: jest.fn(),
      onStreamError: jest.fn(),
    };
    const health = {
      recordWsSuccess: jest.fn(),
      recordWsFailure: jest.fn(),
    };
    const connections = new Map<string, MockSocket>();

    const transportPromise = tryWebSocketTransport({
      conversationId: "conv-ws-3",
      agentId: "agent-1",
      source: "personal",
      payload: { query: "hello" },
      callbacks,
      connections,
      health,
    });

    await flushMicrotasks();
    currentSocket.onopen?.();
    currentSocket.onmessage?.({
      data: JSON.stringify({ kind: "chunk" }),
    });
    await flushMicrotasks();

    jest.advanceTimersByTime(45_000);
    await flushMicrotasks();

    await expect(transportPromise).resolves.toBe(true);
    expect(callbacks.onStreamError).toHaveBeenCalledWith(
      "WebSocket idle timeout after 45000ms",
      "timeout",
    );
    expect(health.recordWsFailure).not.toHaveBeenCalled();
  });
});
