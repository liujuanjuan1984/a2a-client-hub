import { act, renderHook } from "@testing-library/react-native";

import {
  usePersonalAgentsListQuery,
  useSharedAgentsListQuery,
} from "@/hooks/useAgentListQueries";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { listAgentsPage } from "@/lib/api/a2aAgents";
import { listHubAgentsPage } from "@/lib/api/hubA2aAgentsUser";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/api/a2aAgents", () => ({
  listAgentsPage: jest.fn(),
}));

jest.mock("@/lib/api/hubA2aAgentsUser", () => ({
  listHubAgentsPage: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () => ({
  buildPersistStorageName: (key: string) => key,
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

const mockedUsePaginatedList = jest.mocked(usePaginatedList);
const mockedListAgentsPage = jest.mocked(listAgentsPage);
const mockedListHubAgentsPage = jest.mocked(listHubAgentsPage);

const createPaginatedResult = (
  overrides?: Partial<ReturnType<typeof usePaginatedList>>,
): ReturnType<typeof usePaginatedList> =>
  ({
    error: null,
    isError: false,
    pages: [],
    items: [],
    setItems: jest.fn(),
    nextPage: null,
    hasMore: false,
    loading: false,
    refreshing: false,
    loadingMore: false,
    reset: jest.fn(),
    loadFirstPage: jest.fn(async () => true),
    loadMore: jest.fn(async () => {}),
    ...overrides,
  }) as ReturnType<typeof usePaginatedList>;

describe("useAgentListQueries", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult());
    mockedListAgentsPage.mockResolvedValue({
      items: [],
      pagination: { page: 1, size: 12, total: 0, pages: 0 },
      meta: {
        counts: { healthy: 0, degraded: 0, unavailable: 0, unknown: 0 },
      },
      nextPage: undefined,
    });
    mockedListHubAgentsPage.mockResolvedValue({
      items: [],
      pagination: { page: 1, size: 8, total: 0, pages: 0 },
      meta: {},
      nextPage: undefined,
    });
  });

  it("loads personal agents with a stable infinite-list query key", async () => {
    mockedUsePaginatedList.mockReturnValue(
      createPaginatedResult({
        pages: [
          {
            items: [],
            nextPage: undefined,
            pagination: { page: 1, size: 12, total: 0, pages: 0 },
            meta: {
              counts: {
                healthy: 1,
                degraded: 2,
                unavailable: 3,
                unknown: 4,
              },
            },
          },
        ],
      }),
    );

    const { result } = renderHook(() =>
      usePersonalAgentsListQuery({
        size: 10,
        healthBucket: "degraded",
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "agents",
      "list",
      { size: 10, health_bucket: "degraded" },
    ]);

    await options?.fetchPage(2);
    expect(mockedListAgentsPage).toHaveBeenCalledWith({
      page: 2,
      size: 10,
      healthBucket: "degraded",
    });

    expect(result.current.counts).toEqual({
      healthy: 1,
      degraded: 2,
      unavailable: 3,
      unknown: 4,
    });

    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.loadFirstPage).toHaveBeenCalledWith("refreshing");
  });

  it("loads shared agents with a stable infinite-list query key", async () => {
    renderHook(() =>
      useSharedAgentsListQuery({
        size: 8,
        enabled: false,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["agents", "shared-list", { size: 8 }]);
    expect(options?.enabled).toBe(false);

    await options?.fetchPage(3);
    expect(mockedListHubAgentsPage).toHaveBeenCalledWith({
      page: 3,
      size: 8,
    });
  });
});
