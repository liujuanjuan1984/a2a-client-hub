import { renderHook } from "@testing-library/react-native";

import { usePaginatedList } from "@/hooks/usePaginatedList";
import { useScheduledJobExecutionsQuery } from "@/hooks/useScheduledJobExecutionsQuery";
import { listScheduledJobExecutionsPage } from "@/lib/api/scheduledJobs";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/api/scheduledJobs", () => ({
  listScheduledJobExecutionsPage: jest.fn(),
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
const mockedListScheduledJobExecutionsPage = jest.mocked(
  listScheduledJobExecutionsPage,
);

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

describe("useScheduledJobExecutionsQuery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult());
  });

  it("passes execution query key and enabled flag", () => {
    renderHook(() =>
      useScheduledJobExecutionsQuery({
        taskId: "task-1",
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "scheduled-jobs",
      "executions",
      "task-1",
    ]);
    expect(options?.enabled).toBe(true);
  });

  it("disables query when task id is missing", () => {
    renderHook(() =>
      useScheduledJobExecutionsQuery({
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "scheduled-jobs",
      "executions",
      "missing",
    ]);
    expect(options?.enabled).toBe(false);
  });

  it("fetches execution page with expected pagination params", async () => {
    mockedListScheduledJobExecutionsPage.mockResolvedValue({
      items: [{ id: "execution-1" } as any],
      nextPage: 3,
    } as any);

    renderHook(() =>
      useScheduledJobExecutionsQuery({
        taskId: "task-1",
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    if (!options) {
      throw new Error("Paginated options should be available.");
    }

    const result = await options.fetchPage(2);
    expect(mockedListScheduledJobExecutionsPage).toHaveBeenCalledWith(
      "task-1",
      {
        page: 2,
        size: 50,
      },
    );
    expect(result).toEqual({
      items: [{ id: "execution-1" }],
      nextPage: 3,
    });
  });

  it("throws when fetchPage runs without a task id", async () => {
    renderHook(() =>
      useScheduledJobExecutionsQuery({
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    if (!options) {
      throw new Error("Paginated options should be available.");
    }

    await expect(options.fetchPage(1)).rejects.toThrow("Task id is required.");
  });
});
