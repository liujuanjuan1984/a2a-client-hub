import { renderHook } from "@testing-library/react-native";

import { useAgentOpencodeSessionsQuery } from "@/hooks/useAgentOpencodeSessionsQuery";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { A2AExtensionCallError } from "@/lib/api/a2aExtensions";
import { ApiRequestError } from "@/lib/api/client";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

const mockedUsePaginatedList = jest.mocked(usePaginatedList);

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

describe("useAgentOpencodeSessionsQuery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult());
  });

  it("passes query key and enabled flag to paginated list", () => {
    renderHook(() =>
      useAgentOpencodeSessionsQuery({
        agentId: "agent-1",
        source: "shared",
        enabled: false,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "sessions",
      "opencode",
      "shared",
      "agent-1",
    ]);
    expect(options?.enabled).toBe(false);
  });

  it("maps extension and http errors to user-facing messages", () => {
    renderHook(() =>
      useAgentOpencodeSessionsQuery({
        agentId: "agent-1",
        source: "personal",
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];

    const extensionError = new A2AExtensionCallError("ext", {
      errorCode: "upstream_unreachable",
    });
    expect(options?.mapErrorMessage?.(extensionError)).toBe(
      "Upstream is unreachable.",
    );

    const requestError = new ApiRequestError("Bad gateway", 502);
    expect(options?.mapErrorMessage?.(requestError)).toBe(
      "Extension is not supported or the contract is invalid.",
    );
  });
});
