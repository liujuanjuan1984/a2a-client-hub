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

  class MockAuthRecoverableError extends MockApiRequestError {
    constructor(message = "Authentication recovery in progress.") {
      super(message, 503, "auth_recovering");
      this.name = "AuthRecoverableError";
    }
  }

  return {
    AUTH_RECOVERY_MAX_DURATION_MS: 120_000,
    AUTH_RECOVERY_MAX_RETRIES: 12,
    ApiRequestError: MockApiRequestError,
    AuthExpiredError: MockAuthExpiredError,
    AuthRecoverableError: MockAuthRecoverableError,
    ensureFreshAccessToken: jest.fn(async () => null),
    hasExceededAuthRecoveryLimits: jest.fn(() => false),
    handleAuthExpiredOnce: jest.fn(),
    refreshAccessToken: jest.fn(async () => null),
    refreshAccessTokenWithOutcome: jest.fn(async () => ({
      result: null,
      failureReason: "transient",
    })),
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
const clientModule =
  require("@/lib/api/client") as typeof import("@/lib/api/client");

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

  it("does not reset auth state when sse refresh fails transiently after 401", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => "expired",
    } as Response);
    (
      clientModule.refreshAccessTokenWithOutcome as jest.Mock
    ).mockResolvedValueOnce({
      result: null,
      failureReason: "transient",
    });

    const onError = jest.fn();

    await fetchSSE("https://example.test/stream", { onError });

    expect(clientModule.handleAuthExpiredOnce).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "AuthRecoverableError",
        errorCode: "auth_recovering",
      }),
    );
  });

  it("forces logout when sse recovery is already beyond the allowed window", async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 401,
      text: async () => "expired",
    } as Response);
    (
      clientModule.refreshAccessTokenWithOutcome as jest.Mock
    ).mockResolvedValueOnce({
      result: null,
      failureReason: "transient",
    });
    (
      clientModule.hasExceededAuthRecoveryLimits as jest.Mock
    ).mockReturnValueOnce(true);

    const onError = jest.fn();

    await fetchSSE("https://example.test/stream", { onError });

    expect(clientModule.handleAuthExpiredOnce).toHaveBeenCalledTimes(1);
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "AuthExpiredError",
        errorCode: "auth_expired",
      }),
    );
  });
});
