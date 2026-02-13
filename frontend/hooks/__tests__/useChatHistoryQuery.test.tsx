import { renderHook } from "@testing-library/react-native";

import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { CHAT_MESSAGE_HISTORY_LIMIT } from "@/lib/messageHistory";
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
    loadFirstPage: jest.fn(async () => true),
    loadMore: jest.fn(async () => {}),
  }) as ReturnType<typeof usePaginatedList>;

describe("useChatHistoryQuery", () => {
  beforeEach(() => {
    mockedUsePaginatedList.mockReset();
  });

  it("maps session history messages and keeps the latest configured limit", () => {
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

    const firstRetainedIndex = items.length - CHAT_MESSAGE_HISTORY_LIMIT;
    expect(result.current.messages).toHaveLength(CHAT_MESSAGE_HISTORY_LIMIT);
    expect(result.current.messages[0]).toMatchObject({
      id: `msg-${firstRetainedIndex}`,
      role: firstRetainedIndex % 2 === 0 ? "agent" : "user",
      content: `content-${firstRetainedIndex}`,
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
});
