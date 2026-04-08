const createJsonResponse = (status: number, payload: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }) as Response;

const createAbortError = () => {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
};

const createDeferred = <T>() => {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe("api client auth refresh flow", () => {
  const originalApiBaseUrl = process.env.EXPO_PUBLIC_API_BASE_URL;

  beforeEach(() => {
    jest.resetModules();
    process.env.EXPO_PUBLIC_API_BASE_URL = "https://example.test/api/v1";
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.clearAllMocks();
    process.env.EXPO_PUBLIC_API_BASE_URL = originalApiBaseUrl;
  });

  const loadModules = () => {
    const resetAuthBoundState = jest.fn();
    jest.doMock("@/lib/resetClientState", () => ({
      resetAuthBoundState,
    }));

    const client =
      require("@/lib/api/client") as typeof import("@/lib/api/client");
    const sessionStore =
      require("@/store/session") as typeof import("@/store/session");

    return {
      client,
      useSessionStore: sessionStore.useSessionStore,
      resetAuthBoundState,
    };
  };

  it("parses nested refresh payload for access_token and expires_in", async () => {
    const { client } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValue(
      createJsonResponse(200, {
        data: {
          access_token: "nested-token",
          expires_in: 180,
        },
      }),
    );

    const result = await client.refreshAccessToken({ force: true });

    expect(result).toEqual({
      accessToken: "nested-token",
      expiresInSeconds: 180,
    });
  });

  it("adds a native first-party client header outside web", async () => {
    jest.resetModules();
    jest.doMock("react-native", () => {
      const actual = jest.requireActual("react-native");
      return {
        ...actual,
        Platform: {
          ...actual.Platform,
          OS: "ios",
        },
      };
    });

    const { client } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValue(
      createJsonResponse(200, {
        access_token: "native-token",
        expires_in: 120,
      }),
    );

    await client.refreshAccessToken({ force: true });

    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.test/api/v1/auth/refresh",
      expect.objectContaining({
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-A2A-Client-Platform": "native",
        }),
      }),
    );
  });

  it("proactively refreshes and updates session token when token is near expiry", async () => {
    const { client, useSessionStore } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValue(
      createJsonResponse(200, {
        access_token: "new-token",
        expires_in: 300,
      }),
    );

    useSessionStore.setState({
      token: "old-token",
      accessTokenExpiresAtMs: Date.now() + 2_000,
      accessTokenTtlSeconds: 10,
      authStatus: "authenticated",
      recoveryStartedAtMs: Date.now() - 10_000,
      recoveryRetryCount: 3,
    });

    const token = await client.ensureFreshAccessToken();

    expect(token).toBe("new-token");
    expect(useSessionStore.getState().token).toBe("new-token");
    expect(useSessionStore.getState().authStatus).toBe("authenticated");
    expect(useSessionStore.getState().recoveryStartedAtMs).toBeNull();
    expect(useSessionStore.getState().recoveryRetryCount).toBe(0);
  });

  it("keeps current token when proactive refresh fails but token has not expired", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValue(createJsonResponse(401, { detail: "expired" }));

    useSessionStore.setState({
      token: "still-valid-token",
      accessTokenExpiresAtMs: Date.now() + 3_000,
      accessTokenTtlSeconds: 10,
      authStatus: "authenticated",
    });

    const token = await client.ensureFreshAccessToken();

    expect(token).toBe("still-valid-token");
    expect(useSessionStore.getState().token).toBe("still-valid-token");
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("marks auth as recovering when proactive refresh fails transiently", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockRejectedValue(createAbortError());

    useSessionStore.setState({
      token: "still-valid-token",
      accessTokenExpiresAtMs: Date.now() + 3_000,
      accessTokenTtlSeconds: 10,
      authStatus: "authenticated",
    });

    const token = await client.ensureFreshAccessToken();

    expect(token).toBe("still-valid-token");
    expect(useSessionStore.getState().authStatus).toBe("recovering");
    expect(useSessionStore.getState().recoveryStartedAtMs).not.toBeNull();
    expect(useSessionStore.getState().recoveryRetryCount).toBe(1);
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("keeps session and throws recoverable auth error when expired token cannot refresh transiently", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockRejectedValue(createAbortError());

    useSessionStore.setState({
      token: "expired-token",
      accessTokenExpiresAtMs: Date.now() - 1,
      accessTokenTtlSeconds: 10,
      authStatus: "authenticated",
    });

    await expect(client.ensureFreshAccessToken()).rejects.toMatchObject({
      status: 503,
      errorCode: "auth_recovering",
    });

    expect(useSessionStore.getState().token).toBe("expired-token");
    expect(useSessionStore.getState().authStatus).toBe("recovering");
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("counts a shared transient refresh attempt only once", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    const deferred = createDeferred<Response>();
    fetchMock.mockImplementation(() => deferred.promise);

    useSessionStore.setState({
      token: "expired-token",
      accessTokenExpiresAtMs: Date.now() - 1,
      accessTokenTtlSeconds: 10,
      authStatus: "authenticated",
    });

    const firstAttempt = client.ensureFreshAccessToken();
    const secondAttempt = client.ensureFreshAccessToken();

    deferred.reject(createAbortError());

    await expect(firstAttempt).rejects.toMatchObject({
      status: 503,
      errorCode: "auth_recovering",
    });
    await expect(secondAttempt).rejects.toMatchObject({
      status: 503,
      errorCode: "auth_recovering",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useSessionStore.getState().authStatus).toBe("recovering");
    expect(useSessionStore.getState().recoveryStartedAtMs).not.toBeNull();
    expect(useSessionStore.getState().recoveryRetryCount).toBe(1);
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("forces logout when transient recovery exceeds max duration", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockRejectedValue(createAbortError());

    useSessionStore.setState({
      token: "expired-token",
      accessTokenExpiresAtMs: Date.now() - 1,
      accessTokenTtlSeconds: 10,
      authStatus: "recovering",
      recoveryStartedAtMs:
        Date.now() - (client.AUTH_RECOVERY_MAX_DURATION_MS + 1),
      recoveryRetryCount: 1,
    });

    await expect(client.ensureFreshAccessToken()).rejects.toMatchObject({
      status: 401,
      errorCode: "auth_expired",
    });

    expect(resetAuthBoundState).toHaveBeenCalledTimes(1);
  });

  it("forces logout when transient recovery exceeds max retries", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(401, { detail: "expired" }))
      .mockRejectedValueOnce(createAbortError());

    useSessionStore.setState({
      token: "old-token",
      authStatus: "recovering",
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
      recoveryStartedAtMs: Date.now() - 10_000,
      recoveryRetryCount: client.AUTH_RECOVERY_MAX_RETRIES,
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 401,
      errorCode: "auth_expired",
    });

    expect(resetAuthBoundState).toHaveBeenCalledTimes(1);
  });

  it("bypasses refresh cooldown when force=true", async () => {
    const { client, useSessionStore } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(
        createJsonResponse(200, {
          access_token: "forced-token",
          expires_in: 120,
        }),
      );

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
    });

    const firstResult = await client.refreshAccessToken();
    const secondResult = await client.refreshAccessToken({ force: true });

    expect(firstResult).toBeNull();
    expect(secondResult).toEqual({
      accessToken: "forced-token",
      expiresInSeconds: 120,
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not refresh on 403 and keeps current auth session", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(403, { detail: "forbidden" }),
    );

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 403,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(resetAuthBoundState).not.toHaveBeenCalled();
    expect(useSessionStore.getState().token).toBe("old-token");
  });

  it("keeps session when request-side forced refresh fails transiently after a 401", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(401, { detail: "expired" }))
      .mockRejectedValueOnce(createAbortError());

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 503,
      errorCode: "auth_recovering",
    });

    expect(resetAuthBoundState).not.toHaveBeenCalled();
    expect(useSessionStore.getState().token).toBe("old-token");
    expect(useSessionStore.getState().authStatus).toBe("recovering");
  });

  it("clears session when request-side forced refresh is explicitly unauthorized", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock
      .mockResolvedValueOnce(createJsonResponse(401, { detail: "expired" }))
      .mockResolvedValueOnce(createJsonResponse(401, { detail: "expired" }));

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
      accessTokenExpiresAtMs: null,
      accessTokenTtlSeconds: null,
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 401,
      errorCode: "auth_expired",
    });

    expect(resetAuthBoundState).toHaveBeenCalledTimes(1);
  });

  it("does not trigger refresh flow for auth endpoints", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(401, { detail: "login_failed" }),
    );

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
    });

    await expect(
      client.apiRequest<
        { ok: boolean },
        { username: string; password: string }
      >("/auth/login", {
        method: "POST",
        body: { username: "u", password: "p" },
      }),
    ).rejects.toMatchObject({
      status: 401,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("skips refresh flow when Authorization header is explicitly provided", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(401, { detail: "expired" }),
    );

    useSessionStore.setState({
      token: "store-token",
      authStatus: "authenticated",
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo", {
        headers: {
          Authorization: "Bearer override-token",
        },
      }),
    ).rejects.toMatchObject({
      status: 401,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(resetAuthBoundState).not.toHaveBeenCalled();
  });

  it("uses detail.message when backend error payload is an object", async () => {
    const { client, useSessionStore } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(404, {
        detail: {
          message: "session_not_found",
        },
      }),
    );

    useSessionStore.setState({
      token: "token",
      authStatus: "authenticated",
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 404,
      message: "session_not_found",
    });
  });

  it("preserves structured upstream error details on API request errors", async () => {
    const { client, useSessionStore } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce(
      createJsonResponse(400, {
        detail: {
          message: "Upstream streaming failed",
          error_code: "invalid_params",
          source: "upstream_a2a",
          jsonrpc_code: -32602,
          missing_params: [{ name: "project_id", required: true }],
          upstream_error: {
            message: "project_id required",
          },
        },
      }),
    );

    useSessionStore.setState({
      token: "token",
      authStatus: "authenticated",
    });

    await expect(
      client.apiRequest<{ ok: boolean }>("/me/echo"),
    ).rejects.toMatchObject({
      status: 400,
      errorCode: "invalid_params",
      source: "upstream_a2a",
      jsonrpcCode: -32602,
      missingParams: [{ name: "project_id", required: true }],
      upstreamError: {
        message: "project_id required",
      },
    });
  });

  it("shares one refresh request across 20 concurrent callers", async () => {
    const { client, useSessionStore } = loadModules();
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValue(
      createJsonResponse(200, {
        access_token: "single-flight-token",
        expires_in: 600,
      }),
    );

    useSessionStore.setState({
      token: "old-token",
      authStatus: "authenticated",
      accessTokenExpiresAtMs: Date.now() - 1,
      accessTokenTtlSeconds: 30,
    });
    const expectedAuthVersion = useSessionStore.getState().authVersion;

    const results = await Promise.all(
      Array.from({ length: 20 }, () =>
        client.refreshAccessToken({ expectedAuthVersion }),
      ),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    results.forEach((item) => {
      expect(item?.accessToken).toBe("single-flight-token");
      expect(item?.expiresInSeconds).toBe(600);
    });
  });

  it("ignores stale auth-expired handling when authVersion has changed", async () => {
    const { client, useSessionStore, resetAuthBoundState } = loadModules();
    useSessionStore.setState({
      token: "v1-token",
      authStatus: "authenticated",
      authVersion: 1,
    });

    useSessionStore.getState().setAccessToken("v2-token", 120);
    expect(useSessionStore.getState().authVersion).toBe(2);

    client.handleAuthExpiredOnce({ expectedAuthVersion: 1 });

    expect(resetAuthBoundState).not.toHaveBeenCalled();
    expect(useSessionStore.getState().token).toBe("v2-token");
  });
});
