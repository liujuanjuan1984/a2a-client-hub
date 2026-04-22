import { useQuery } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react-native";

import { useSessionUpstreamTaskQuery } from "@/hooks/useSessionUpstreamTaskQuery";
import { getSessionUpstreamTask } from "@/lib/api/sessions";

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
}));

jest.mock("@/lib/api/sessions", () => ({
  getSessionUpstreamTask: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () =>
  require("@/test-utils/mockMmkv").createMockMmkvModule(),
);

const mockedUseQuery = jest.mocked(useQuery);
const mockedGetSessionUpstreamTask = jest.mocked(getSessionUpstreamTask);

describe("useSessionUpstreamTaskQuery", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseQuery.mockReturnValue({} as ReturnType<typeof useQuery>);
  });

  it("enables an on-demand task query with normalized ids", async () => {
    renderHook(() =>
      useSessionUpstreamTaskQuery({
        conversationId: " conv-1 ",
        taskId: " task-1 ",
        historyLength: 3.9,
      }),
    );

    const options = mockedUseQuery.mock.calls[0]?.[0];
    expect(options?.enabled).toBe(true);
    expect(options?.queryKey).toEqual([
      "sessions",
      "upstream-task",
      "conv-1",
      "task-1",
      3,
    ]);
    expect(options?.refetchInterval).toBe(false);
    expect(options?.refetchOnWindowFocus).toBe(false);

    const queryFn = options?.queryFn as (() => Promise<unknown>) | undefined;
    await queryFn?.();
    expect(mockedGetSessionUpstreamTask).toHaveBeenCalledWith(
      "conv-1",
      "task-1",
      { historyLength: 3 },
    );
  });

  it("stays disabled until both ids are available", () => {
    renderHook(() =>
      useSessionUpstreamTaskQuery({
        conversationId: "conv-1",
        taskId: " ",
      }),
    );

    const options = mockedUseQuery.mock.calls[0]?.[0];
    expect(options?.enabled).toBe(false);
    expect(options?.queryKey).toEqual(["sessions", "upstream-task", "idle"]);
  });
});
