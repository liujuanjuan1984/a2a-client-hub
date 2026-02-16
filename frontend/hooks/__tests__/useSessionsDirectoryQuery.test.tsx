import { act, renderHook } from "@testing-library/react-native";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { useSessionsDirectoryQuery } from "@/hooks/useSessionsDirectoryQuery";
import { listSessionsPage } from "@/lib/api/sessions";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/api/sessions", () => ({
  listSessionsPage: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

const mockedUsePaginatedList = jest.mocked(usePaginatedList);
const mockedListDirectoryPage = jest.mocked(listSessionsPage);

const createPaginatedResult = (): ReturnType<typeof usePaginatedList> =>
  ({
    error: null,
    isError: false,
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

describe("useSessionsDirectoryQuery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult());
    mockedListDirectoryPage.mockResolvedValue({
      items: [],
      nextPage: undefined,
      pagination: null,
      meta: null,
    });
  });

  it("uses directory key and fetches pages with stable query params", async () => {
    const { result } = renderHook(() => useSessionsDirectoryQuery());

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["sessions", "directory"]);

    await options?.fetchPage(1);
    expect(mockedListDirectoryPage).toHaveBeenNthCalledWith(1, {
      page: 1,
      size: 50,
    });

    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.loadFirstPage).toHaveBeenCalledWith("refreshing");

    await options?.fetchPage(1);
    expect(mockedListDirectoryPage).toHaveBeenNthCalledWith(2, {
      page: 1,
      size: 50,
    });
  });
});
