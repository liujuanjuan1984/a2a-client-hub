jest.mock("react-native", () => ({
  Platform: {
    OS: "web",
  },
}));

const OriginalWebSocket = globalThis.WebSocket;
let consoleInfoSpy: jest.SpyInstance;

beforeAll(() => {
  const MockWebSocket = jest.fn() as unknown as typeof WebSocket;
  globalThis.WebSocket = MockWebSocket;
});

afterAll(() => {
  globalThis.WebSocket = OriginalWebSocket;
});

describe("ChatTransportHealth", () => {
  beforeEach(() => {
    consoleInfoSpy = jest.spyOn(console, "info").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleInfoSpy.mockRestore();
  });

  it("prefers ws, then sse, then http_json based on health state", () => {
    const { ChatTransportHealth } =
      require("@/services/chatTransportHealth") as {
        ChatTransportHealth: new () => {
          getPreferredTransport: () => string;
          recordWsFailure: (error: unknown) => void;
          recordSseFailure: (error: unknown) => void;
          recordWsSuccess: () => void;
        };
      };

    const health = new ChatTransportHealth();

    expect(health.getPreferredTransport()).toBe("ws");

    health.recordWsFailure(new Error("ws-down-1"));
    health.recordWsFailure(new Error("ws-down-2"));
    expect(health.getPreferredTransport()).toBe("http_sse");

    health.recordSseFailure(new Error("sse-down-1"));
    health.recordSseFailure(new Error("sse-down-2"));
    expect(health.getPreferredTransport()).toBe("http_json");

    health.recordWsSuccess();
    expect(health.getPreferredTransport()).toBe("ws");
  });
});
