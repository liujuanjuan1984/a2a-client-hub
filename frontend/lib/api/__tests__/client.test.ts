const createJsonResponse = (status: number, payload: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  }) as Response;

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
      resetClientState: jest.fn(),
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
    });

    const token = await client.ensureFreshAccessToken();

    expect(token).toBe("new-token");
    expect(useSessionStore.getState().token).toBe("new-token");
    expect(useSessionStore.getState().authStatus).toBe("authenticated");
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
});
