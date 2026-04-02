import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import React from "react";

import { usePersonalAgentsListQuery } from "@/hooks/useAgentListQueries";
import { listAgentsPage } from "@/lib/api/a2aAgents";

jest.mock("@/lib/storage/mmkv", () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

jest.mock("@/store/session", () => ({
  useSessionStore: (selector: any) =>
    selector({
      user: { id: "user-1" },
      token: "token-1",
    }),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  listAgentsPage: jest.fn(),
}));

const mockedListAgentsPage = jest.mocked(listAgentsPage);

describe("AgentListScreen pagination with zero pages", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
    jest.clearAllMocks();
  });

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("ensures page is never 0 even when server returns pages=0", async () => {
    // Mock server returning 0 items and 0 pages
    mockedListAgentsPage.mockResolvedValue({
      items: [],
      pagination: { page: 1, size: 12, total: 0, pages: 0 },
      meta: {
        counts: { healthy: 0, degraded: 0, unavailable: 0, unknown: 0 },
      },
      nextPage: undefined,
    });

    const { result } = renderHook(
      () =>
        usePersonalAgentsListQuery({
          size: 12,
          healthBucket: "healthy",
        }),
      { wrapper },
    );

    // Initial load should be page 1
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mockedListAgentsPage).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    );

    // Verify parsed results don't have page 0
    const firstPage = result.current.pages[0];
    expect(firstPage.pagination.page).toBeGreaterThanOrEqual(1);
    expect(firstPage.pagination.pages).toBe(0);

    // Now try to refresh or load more
    await act(async () => {
      await result.current.refresh();
    });

    // Verify it still requests page 1, not 0
    expect(mockedListAgentsPage).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1 }),
    );
    expect(mockedListAgentsPage).not.toHaveBeenCalledWith(
      expect.objectContaining({ page: 0 }),
    );
  });
});
