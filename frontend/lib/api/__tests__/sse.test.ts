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

  class MockAuthExpiredError extends MockApiRequestError {
    constructor(message = "Authentication expired.") {
      super(message, 401, "auth_expired");
      this.name = "AuthExpiredError";
    }
  }

  return {
    ApiRequestError: MockApiRequestError,
    AuthExpiredError: MockAuthExpiredError,
    ensureFreshAccessToken: jest.fn(async () => null),
    handleAuthExpiredOnce: jest.fn(),
    refreshAccessToken: jest.fn(async () => null),
  };
});

jest.mock("@/store/session", () => ({
  useSessionStore: {
    getState: () => ({
      authVersion: 1,
      token: null,
      setAccessToken: jest.fn(),
      setAuthStatus: jest.fn(),
    }),
  },
}));

const { fetchSSE, SSEStreamError } =
  require("@/lib/api/sse") as typeof import("@/lib/api/sse");

const createSseResponse = (payload: string): Response =>
  ({
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(payload));
        controller.close();
      },
    }),
  }) as Response;

describe("fetchSSE", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it("parses structured error events with error_code", async () => {
    (global.fetch as jest.Mock).mockResolvedValue(
      createSseResponse(
        'event: error\ndata: {"message":"Upstream streaming failed","error_code":"agent_unavailable"}\n\n',
      ),
    );

    const onError = jest.fn();

    await fetchSSE(
      "https://example.test/stream",
      {
        onError,
      },
      {
        body: { query: "hello" },
      },
    );

    expect(onError).toHaveBeenCalledTimes(1);
    const error = onError.mock.calls[0]?.[0];
    expect(error).toBeInstanceOf(SSEStreamError);
    expect(error).toMatchObject({
      message: "Upstream streaming failed",
      errorCode: "agent_unavailable",
    });
  });
});
