jest.mock("@/lib/api/client", () => {
  class MockApiRequestError extends Error {
    status: number;
    errorCode: string | null;
    source: string | null;
    jsonrpcCode: number | null;
    missingParams: { name: string; required: boolean }[] | null;
    upstreamError: Record<string, unknown> | null;

    constructor(
      message: string,
      status: number,
      options:
        | string
        | {
            errorCode?: string | null;
            source?: string | null;
            jsonrpcCode?: number | null;
            missingParams?: { name: string; required: boolean }[] | null;
            upstreamError?: Record<string, unknown> | null;
          }
        | null = null,
    ) {
      super(message);
      this.name = "ApiRequestError";
      this.status = status;
      if (typeof options === "string" || options == null) {
        this.errorCode = options ?? null;
        this.source = null;
        this.jsonrpcCode = null;
        this.missingParams = null;
        this.upstreamError = null;
        return;
      }
      this.errorCode = options.errorCode ?? null;
      this.source = options.source ?? null;
      this.jsonrpcCode = options.jsonrpcCode ?? null;
      this.missingParams = options.missingParams ?? null;
      this.upstreamError = options.upstreamError ?? null;
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
    handleAuthExpiredOnce: jest.fn(),
    parseApiErrorResponse: jest.fn(async (response: Response) => {
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      const detail =
        payload && typeof payload === "object" && "detail" in payload
          ? (payload as { detail?: unknown }).detail
          : null;
      const detailRecord =
        detail && typeof detail === "object" && !Array.isArray(detail)
          ? (detail as Record<string, unknown>)
          : null;
      return {
        message:
          (detailRecord &&
            typeof detailRecord.message === "string" &&
            detailRecord.message) ||
          `Request failed (${response.status})`,
        errorCode:
          detailRecord && typeof detailRecord.error_code === "string"
            ? detailRecord.error_code
            : null,
        source:
          detailRecord && typeof detailRecord.source === "string"
            ? detailRecord.source
            : null,
        jsonrpcCode:
          detailRecord && typeof detailRecord.jsonrpc_code === "number"
            ? detailRecord.jsonrpc_code
            : null,
        missingParams:
          detailRecord && Array.isArray(detailRecord.missing_params)
            ? (detailRecord.missing_params as {
                name: string;
                required: boolean;
              }[])
            : null,
        upstreamError:
          detailRecord &&
          detailRecord.upstream_error &&
          typeof detailRecord.upstream_error === "object" &&
          !Array.isArray(detailRecord.upstream_error)
            ? (detailRecord.upstream_error as Record<string, unknown>)
            : null,
      };
    }),
    refreshAccessToken: jest.fn(async () => null),
    refreshAccessTokenWithOutcome: jest.fn(async () => ({
      result: null,
      failureReason: "transient",
      didExpireSession: false,
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
        'event: error\ndata: {"message":"Upstream streaming failed","error_code":"invalid_params","source":"upstream_a2a","jsonrpc_code":-32602,"missing_params":[{"name":"project_id","required":true}],"upstream_error":{"message":"project_id required"}}\n\n',
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
      errorCode: "invalid_params",
      source: "upstream_a2a",
      jsonrpcCode: -32602,
      missingParams: [{ name: "project_id", required: true }],
      upstreamError: { message: "project_id required" },
    });
  });

  it("parses non-2xx SSE handshake failures into structured ApiRequestError", async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({
        detail: {
          message: "Outbound A2A URL is not allowed",
          error_code: "outbound_not_allowed",
          source: "hub_policy",
        },
      }),
    } as Response);

    const onError = jest.fn();

    await fetchSSE("https://example.test/stream", { onError });

    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "ApiRequestError",
        status: 403,
        errorCode: "outbound_not_allowed",
        source: "hub_policy",
        message: "Outbound A2A URL is not allowed",
      }),
    );
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
      didExpireSession: false,
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
    ).mockImplementationOnce(async () => {
      clientModule.handleAuthExpiredOnce();
      return {
        result: null,
        failureReason: "transient",
        didExpireSession: true,
      };
    });

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
