import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import {
  usePersonalAgentsListQuery,
  useSharedAgentsListQuery,
} from "@/hooks/useAgentListQueries";
import { queryKeys } from "@/lib/queryKeys";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

const mocks = {
  listAgents: jest.fn(),
  listHubAgents: jest.fn(),
};

jest.mock("@/lib/api/a2aAgents", () => ({
  listAgents: (...args: unknown[]) => mocks.listAgents(...args),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  listHubAgents: (...args: unknown[]) => mocks.listHubAgents(...args),
}));

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("useAgentListQueries", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
    jest.clearAllMocks();
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("loads personal agents with the requested health bucket", async () => {
    mocks.listAgents.mockResolvedValue({
      items: [],
      pagination: { page: 2, size: 10, total: 0, pages: 0 },
      meta: {
        counts: { healthy: 0, degraded: 0, unavailable: 0, unknown: 0 },
      },
    });

    const { result } = renderHook(
      () =>
        usePersonalAgentsListQuery({
          page: 2,
          size: 10,
          healthBucket: "degraded",
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mocks.listAgents).toHaveBeenCalledWith(2, 10, "degraded");
    expect(
      queryKeys.agents.list({ page: 2, size: 10, healthBucket: "degraded" }),
    ).toEqual([
      "agents",
      "list",
      { page: 2, size: 10, health_bucket: "degraded" },
    ]);
  });

  it("loads shared agents with paginated query keys", async () => {
    mocks.listHubAgents.mockResolvedValue({
      items: [],
      pagination: { page: 3, size: 8, total: 0, pages: 0 },
      meta: {},
    });

    const { result } = renderHook(
      () =>
        useSharedAgentsListQuery({
          page: 3,
          size: 8,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(mocks.listHubAgents).toHaveBeenCalledWith(3, 8);
    expect(queryKeys.agents.sharedList({ page: 3, size: 8 })).toEqual([
      "agents",
      "shared-list",
      { page: 3, size: 8 },
    ]);
  });
});
