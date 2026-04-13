import { renderHook } from "@testing-library/react-native";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { useScheduledJobsQuery } from "@/hooks/useScheduledJobsQuery";
import { ApiRequestError } from "@/lib/api/client";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () =>
  require("@/test-utils/mockMmkv").createMockMmkvModule(),
);

const mockedUsePaginatedList = jest.mocked(usePaginatedList);

const createPaginatedResult = (): ReturnType<typeof usePaginatedList> =>
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
  }) as ReturnType<typeof usePaginatedList>;

describe("useScheduledJobsQuery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult());
  });

  it("passes scheduled jobs key and enabled option", () => {
    renderHook(() => useScheduledJobsQuery({ enabled: false }));

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["scheduled-jobs", "list"]);
    expect(options?.enabled).toBe(false);
  });

  it("maps 503 error to disabled integration message", () => {
    renderHook(() => useScheduledJobsQuery());

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    const error503 = new ApiRequestError("Service unavailable", 503);

    expect(options?.mapErrorMessage?.(error503)).toBe(
      "A2A integration is disabled.",
    );
  });
});
