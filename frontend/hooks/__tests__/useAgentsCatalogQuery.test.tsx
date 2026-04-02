import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import {
  useAgentsCatalogQuery,
  useCreateAgentMutation,
  useDeleteAgentMutation,
  useUpdateAgentMutation,
  useValidateAgentMutation,
} from "@/hooks/useAgentsCatalogQuery";
import { ApiRequestError } from "@/lib/api/client";
import { queryKeys } from "@/lib/queryKeys";
import { type AgentConfig, useAgentStore } from "@/store/agents";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

const mocks = {
  checkAgentHealth: jest.fn(),
  createAgent: jest.fn(),
  deleteAgent: jest.fn(),
  listAgents: jest.fn(),
  updateAgent: jest.fn(),
  validateAgentCard: jest.fn(),
  listHubAgents: jest.fn(),
  validateHubAgentCard: jest.fn(),
};

jest.mock("@/lib/storage/mmkv", () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  checkAgentHealth: (...args: unknown[]) => mocks.checkAgentHealth(...args),
  createAgent: (...args: unknown[]) => mocks.createAgent(...args),
  deleteAgent: (...args: unknown[]) => mocks.deleteAgent(...args),
  listAgents: (...args: unknown[]) => mocks.listAgents(...args),
  updateAgent: (...args: unknown[]) => mocks.updateAgent(...args),
  validateAgentCard: (...args: unknown[]) => mocks.validateAgentCard(...args),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  listHubAgents: (...args: unknown[]) => mocks.listHubAgents(...args),
  validateHubAgentCard: (...args: unknown[]) =>
    mocks.validateHubAgentCard(...args),
}));

const buildAgent = (overrides: Partial<AgentConfig> = {}): AgentConfig => ({
  id: "agent-1",
  source: "personal",
  name: "Agent One",
  cardUrl: "https://example.com/agent-1.json",
  authType: "none",
  bearerToken: "",
  apiKeyHeader: "X-API-Key",
  apiKeyValue: "",
  basicUsername: "",
  basicPassword: "",
  extraHeaders: [],
  status: "idle",
  ...overrides,
});

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const originalConsoleError = console.error;

beforeAll(() => {
  jest.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    const first = args[0];
    if (
      typeof first === "string" &&
      (first.includes("react-test-renderer is deprecated") ||
        first.includes("not wrapped in act"))
    ) {
      return;
    }
    originalConsoleError(...args);
  });
});

afterAll(() => {
  (console.error as jest.Mock).mockRestore();
});

describe("useAgentsCatalogQuery mutations", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    jest.clearAllMocks();
    useAgentStore.setState({ activeAgentId: null });
  });

  it("does not hydrate editable basic username from server hint", async () => {
    mocks.listAgents.mockResolvedValue({
      items: [
        {
          id: "agent-basic",
          name: "Basic Agent",
          card_url: "https://example.com/basic.json",
          auth_type: "basic",
          username_hint: "alice",
          enabled: true,
          tags: [],
          extra_headers: {},
          created_at: "2026-02-12T00:00:00.000Z",
          updated_at: "2026-02-12T00:01:00.000Z",
        },
      ],
    });
    mocks.listHubAgents.mockResolvedValue({ items: [] });

    const { result } = renderHook(() => useAgentsCatalogQuery(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => {
      expect(result.current.data).toEqual([
        expect.objectContaining({
          id: "agent-basic",
          authType: "basic",
          basicUsername: "",
        }),
      ]);
    });
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("updates cache and clears active agent on delete", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({ id: "agent-1" }),
      buildAgent({ id: "agent-2", source: "shared" }),
    ]);
    useAgentStore.setState({ activeAgentId: "agent-1" });
    mocks.deleteAgent.mockResolvedValue({});

    const { result } = renderHook(() => useDeleteAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync("agent-1");
    });

    expect(mocks.deleteAgent).toHaveBeenCalledWith("agent-1");
    expect(
      queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
    ).toEqual([buildAgent({ id: "agent-2", source: "shared" })]);
    expect(useAgentStore.getState().activeAgentId).toBeNull();
    expect(
      queryClient.getQueryState(queryKeys.agents.catalog())?.isInvalidated,
    ).toBe(false);
  });

  it("clears transient validation state when an update changes the card identity", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({
        id: "agent-1",
        status: "error",
        lastError: "network",
        lastCheckedAt: "2026-02-12T00:00:00.000Z",
      }),
    ]);

    mocks.updateAgent.mockResolvedValue({
      id: "agent-1",
      name: "Renamed Agent",
      card_url: "https://example.com/renamed.json",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
      created_at: "2026-02-12T00:00:00.000Z",
      updated_at: "2026-02-12T00:01:00.000Z",
    });

    const { result } = renderHook(() => useUpdateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({
        id: "agent-1",
        payload: { name: "Renamed Agent" },
      });
    });

    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );

    expect(cached?.[0]).toMatchObject({
      id: "agent-1",
      name: "Renamed Agent",
      cardUrl: "https://example.com/renamed.json",
      status: "idle",
      lastError: undefined,
      lastCheckedAt: undefined,
    });
    expect(
      queryClient.getQueryState(queryKeys.agents.catalog())?.isInvalidated,
    ).toBe(false);
  });

  it("preserves transient validation state when an update keeps the same card identity", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({
        id: "agent-1",
        status: "error",
        lastError: "network",
        lastCheckedAt: "2026-02-12T00:00:00.000Z",
      }),
    ]);

    mocks.updateAgent.mockResolvedValue({
      id: "agent-1",
      name: "Renamed Agent",
      card_url: "https://example.com/agent-1.json",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
      created_at: "2026-02-12T00:00:00.000Z",
      updated_at: "2026-02-12T00:01:00.000Z",
    });

    const { result } = renderHook(() => useUpdateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({
        id: "agent-1",
        payload: { name: "Renamed Agent" },
      });
    });

    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );

    expect(cached?.[0]).toMatchObject({
      id: "agent-1",
      name: "Renamed Agent",
      cardUrl: "https://example.com/agent-1.json",
      status: "error",
      lastError: "network",
      lastCheckedAt: "2026-02-12T00:00:00.000Z",
    });
  });

  it("removes missing agent during validate and clears active selection", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({ id: "agent-1" }),
    ]);
    useAgentStore.setState({ activeAgentId: "agent-1" });

    mocks.validateAgentCard.mockRejectedValue(
      new ApiRequestError("Request failed (404)", 404),
    );

    const { result } = renderHook(() => useValidateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    let thrown: unknown;
    await act(async () => {
      try {
        await result.current.mutateAsync("agent-1");
      } catch (error) {
        thrown = error;
      }
    });

    expect(thrown).toBeInstanceOf(Error);
    expect((thrown as Error).message).toBe(
      "Agent no longer exists. Please refresh the list.",
    );
    expect(
      queryClient.getQueryData<AgentConfig[]>(queryKeys.agents.catalog()),
    ).toEqual([]);
    expect(useAgentStore.getState().activeAgentId).toBeNull();
  });

  it("stores validation success metadata after successful validation", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({ id: "agent-1" }),
    ]);

    mocks.validateAgentCard.mockResolvedValue({
      success: true,
      message: "ok",
      card: {
        capabilities: {
          extensions: [
            {
              uri: "urn:a2a:session-binding/v1",
              params: {
                metadata_field: "metadata.shared.session.id",
              },
            },
          ],
        },
      },
    });

    const { result } = renderHook(() => useValidateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync("agent-1");
    });

    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );
    expect(cached?.[0]).toMatchObject({
      id: "agent-1",
      status: "success",
      lastError: undefined,
    });
    expect(typeof cached?.[0]?.lastCheckedAt).toBe("string");
  });

  it("keeps warning-only validation responses in success state", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({ id: "agent-1" }),
    ]);

    mocks.validateAgentCard.mockResolvedValue({
      success: true,
      message: "Agent card validated with warnings",
      validation_warnings: ["Field 'skills' array is empty."],
    });

    const { result } = renderHook(() => useValidateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync("agent-1");
    });

    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );
    expect(cached?.[0]).toMatchObject({
      id: "agent-1",
      status: "success",
      lastError: undefined,
    });
    expect(typeof cached?.[0]?.lastCheckedAt).toBe("string");
  });

  it("appends newly created agent to cache without full refetch", async () => {
    queryClient.setQueryData(queryKeys.agents.catalog(), [
      buildAgent({ id: "shared-1", source: "shared" }),
    ]);

    mocks.createAgent.mockResolvedValue({
      id: "agent-new",
      name: "New Agent",
      card_url: "https://example.com/new.json",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
      created_at: "2026-02-12T00:00:00.000Z",
      updated_at: "2026-02-12T00:00:00.000Z",
    });
    mocks.checkAgentHealth.mockResolvedValue({
      summary: {
        requested: 1,
        checked: 1,
        skipped_cooldown: 0,
        healthy: 1,
        degraded: 0,
        unavailable: 0,
        unknown: 0,
      },
      items: [
        {
          agent_id: "agent-new",
          health_status: "healthy",
          checked_at: "2026-02-12T00:00:05.000Z",
          skipped_cooldown: false,
          error: null,
        },
      ],
    });

    const { result } = renderHook(() => useCreateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await result.current.mutateAsync({
        name: "New Agent",
        cardUrl: "https://example.com/new.json",
        authType: "none",
        bearerToken: "",
        apiKeyHeader: "X-API-Key",
        apiKeyValue: "",
        basicUsername: "",
        basicPassword: "",
        extraHeaders: [],
      });
    });

    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );
    expect(mocks.checkAgentHealth).toHaveBeenCalledWith("agent-new", true);
    expect(cached?.[0]).toMatchObject({ id: "agent-new", source: "personal" });
    expect(cached?.[1]).toMatchObject({ id: "shared-1", source: "shared" });
    expect(
      queryClient.getQueryState(queryKeys.agents.catalog())?.isInvalidated,
    ).toBe(false);
  });

  it("keeps create successful when the follow-up health check fails", async () => {
    mocks.createAgent.mockResolvedValue({
      id: "agent-new",
      name: "New Agent",
      card_url: "https://example.com/new.json",
      auth_type: "none",
      enabled: true,
      tags: [],
      extra_headers: {},
      created_at: "2026-02-12T00:00:00.000Z",
      updated_at: "2026-02-12T00:00:00.000Z",
    });
    mocks.checkAgentHealth.mockRejectedValue(new Error("upstream unavailable"));

    const { result } = renderHook(() => useCreateAgentMutation(), {
      wrapper: createWrapper(queryClient),
    });

    await act(async () => {
      await expect(
        result.current.mutateAsync({
          name: "New Agent",
          cardUrl: "https://example.com/new.json",
          authType: "none",
          bearerToken: "",
          apiKeyHeader: "X-API-Key",
          apiKeyValue: "",
          basicUsername: "",
          basicPassword: "",
          extraHeaders: [],
        }),
      ).resolves.toMatchObject({
        id: "agent-new",
      });
    });

    expect(mocks.checkAgentHealth).toHaveBeenCalledWith("agent-new", true);
    const cached = queryClient.getQueryData<AgentConfig[]>(
      queryKeys.agents.catalog(),
    );
    expect(cached).toEqual([
      expect.objectContaining({
        id: "agent-new",
        source: "personal",
      }),
    ]);
  });
});
