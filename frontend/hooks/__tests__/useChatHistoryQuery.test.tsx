import { renderHook } from "@testing-library/react-native";

import {
  useOpencodeHistoryQuery,
  useSessionHistoryQuery,
} from "@/hooks/useChatHistoryQuery";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { type SessionMessageItem } from "@/lib/sessionHistory";

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

const createPaginatedResult = (
  items: unknown[],
): ReturnType<typeof usePaginatedList> =>
  ({
    error: null,
    isError: false,
    items,
    setItems: jest.fn(),
    nextPage: null,
    hasMore: false,
    loading: false,
    refreshing: false,
    loadingMore: false,
    reset: jest.fn(),
    loadFirstPage: jest.fn(async () => {}),
    loadMore: jest.fn(async () => {}),
  }) as ReturnType<typeof usePaginatedList>;

describe("useChatHistoryQuery", () => {
  beforeEach(() => {
    mockedUsePaginatedList.mockReset();
  });

  it("maps session history messages and keeps the latest 500", () => {
    const items: SessionMessageItem[] = Array.from({ length: 520 }, (_, i) => {
      const minute = String(Math.floor(i / 60)).padStart(2, "0");
      const second = String(i % 60).padStart(2, "0");
      return {
        id: `msg-${i}`,
        role: i % 2 === 0 ? "assistant" : "user",
        content: `content-${i}`,
        created_at: `2026-02-12T00:${minute}:${second}.000Z`,
      };
    });

    mockedUsePaginatedList.mockReturnValue(createPaginatedResult(items));

    const { result } = renderHook(() =>
      useSessionHistoryQuery({
        sessionId: "session-1",
        enabled: true,
      }),
    );

    expect(result.current.messages).toHaveLength(500);
    expect(result.current.messages[0]).toMatchObject({
      id: "msg-20",
      role: "agent",
      content: "content-20",
    });

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["history", "chat", "session-1"]);
    expect(options?.enabled).toBe(true);
  });

  it("disables session history query when session id is missing", () => {
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult([]));

    const { result } = renderHook(() =>
      useSessionHistoryQuery({
        enabled: true,
      }),
    );

    expect(result.current.messages).toEqual([]);
    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["history", "chat", "missing"]);
    expect(options?.enabled).toBe(false);
  });

  it("maps and sorts OpenCode history messages", () => {
    const items = [
      {
        id: "m-2",
        role: "assistant",
        content: "second",
        created_at: "2026-02-12T00:00:02.000Z",
      },
      {
        id: "m-1",
        role: "user",
        content: "first",
        created_at: "2026-02-12T00:00:01.000Z",
      },
    ];

    mockedUsePaginatedList.mockReturnValue(createPaginatedResult(items));

    const { result } = renderHook(() =>
      useOpencodeHistoryQuery({
        agentId: "agent-1",
        sessionId: "oc-session-1",
        source: "personal",
        enabled: true,
      }),
    );

    expect(result.current.messages.map((message) => message.id)).toEqual([
      "opencode:m-1",
      "opencode:m-2",
    ]);

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "history",
      "opencode",
      "personal",
      "agent-1",
      "oc-session-1",
    ]);
    expect(options?.enabled).toBe(true);
  });

  it("disables OpenCode history query when required ids are missing", () => {
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult([]));

    renderHook(() =>
      useOpencodeHistoryQuery({
        source: "shared",
        enabled: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual([
      "history",
      "opencode",
      "shared",
      "missing-agent",
      "missing-session",
    ]);
    expect(options?.enabled).toBe(false);
  });
});
