import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { type PropsWithChildren } from "react";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import {
  cleanupTestQueryClient,
  createTestQueryClient,
} from "@/test-utils/queryClient";

jest.mock("@/lib/toast", () => ({
  toast: {
    error: jest.fn(),
    info: jest.fn(),
    success: jest.fn(),
  },
}));

jest.mock("@/lib/storage/mmkv", () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

type Item = { id: string };

const createWrapper = (queryClient: QueryClient) => {
  return ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe("usePaginatedList", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = createTestQueryClient();
  });

  afterEach(async () => {
    await cleanupTestQueryClient(queryClient);
  });

  it("keeps loadFirstPage stable across query state changes", async () => {
    const fetchPage = jest.fn(async (page: number) => {
      if (page === 1) {
        return {
          items: [{ id: "item-1" }],
          nextPage: 2,
        };
      }
      return {
        items: [{ id: "item-2" }],
      };
    });

    const { result } = renderHook(
      () =>
        usePaginatedList<Item>({
          queryKey: ["test", "stable-load-first-page"],
          fetchPage,
          getKey: (item) => item.id,
          errorTitle: "Load failed",
          fallbackMessage: "Load failed.",
          enabled: true,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    const loadFirstPageBefore = result.current.loadFirstPage;

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.loadMore();
    });

    await waitFor(() => {
      expect(result.current.items).toHaveLength(2);
    });

    expect(result.current.loadFirstPage).toBe(loadFirstPageBefore);
  });

  it("returns false when loadFirstPage fails", async () => {
    const fetchPage = jest.fn(async () => {
      throw new Error("boom");
    });

    const { result } = renderHook(
      () =>
        usePaginatedList<Item>({
          queryKey: ["test", "error"],
          fetchPage,
          getKey: (item) => item.id,
          errorTitle: "Load failed",
          fallbackMessage: "Load failed.",
          enabled: false,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    let succeeded = true;
    await act(async () => {
      succeeded = await result.current.loadFirstPage("refreshing");
    });

    expect(succeeded).toBe(false);
  });

  it("refreshes only the first loaded page", async () => {
    const fetchPage = jest.fn(async (page: number) => {
      if (page === 1) {
        return {
          items: [{ id: "item-1" }],
          nextPage: 2,
        };
      }

      if (page === 2) {
        return {
          items: [{ id: "item-2" }],
        };
      }

      return {
        items: [],
      };
    });

    const { result } = renderHook(
      () =>
        usePaginatedList<Item>({
          queryKey: ["test", "refresh"],
          fetchPage,
          getKey: (item) => item.id,
          errorTitle: "Load failed",
          fallbackMessage: "Load failed.",
          enabled: true,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await waitFor(() => {
      expect(result.current.hasMore).toBe(true);
    });

    await act(async () => {
      await result.current.loadMore();
    });

    await waitFor(() => {
      expect(result.current.items).toHaveLength(2);
    });

    const callsBeforeRefresh = fetchPage.mock.calls.length;

    await act(async () => {
      const succeeded = await result.current.loadFirstPage("refreshing");
      expect(succeeded).toBe(true);
    });

    const refreshCalls = fetchPage.mock.calls
      .slice(callsBeforeRefresh)
      .map((args) => args[0]);

    expect(refreshCalls).toEqual([1]);
  });

  it("restores previously loaded pages when refresh fails", async () => {
    let failRefresh = false;

    const fetchPage = jest.fn(async (page: number) => {
      if (page === 1) {
        if (failRefresh) {
          throw new Error("refresh failed");
        }
        return {
          items: [{ id: "item-1" }],
          nextPage: 2,
        };
      }

      if (page === 2) {
        return {
          items: [{ id: "item-2" }],
        };
      }

      return {
        items: [],
      };
    });

    const { result } = renderHook(
      () =>
        usePaginatedList<Item>({
          queryKey: ["test", "rollback"],
          fetchPage,
          getKey: (item) => item.id,
          errorTitle: "Load failed",
          fallbackMessage: "Load failed.",
          enabled: true,
        }),
      { wrapper: createWrapper(queryClient) },
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    await act(async () => {
      await result.current.loadMore();
    });

    await waitFor(() => {
      expect(result.current.items).toHaveLength(2);
    });

    failRefresh = true;

    await act(async () => {
      const succeeded = await result.current.loadFirstPage("refreshing");
      expect(succeeded).toBe(false);
    });

    await waitFor(() => {
      expect(result.current.items).toHaveLength(2);
      expect(result.current.items.map((item) => item.id)).toEqual([
        "item-1",
        "item-2",
      ]);
    });
  });
});
