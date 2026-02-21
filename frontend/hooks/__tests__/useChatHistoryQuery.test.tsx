import { renderHook } from "@testing-library/react-native";

import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
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
    loadFirstPage: jest.fn(async () => true),
    loadMore: jest.fn(async () => {}),
  }) as ReturnType<typeof usePaginatedList>;

describe("useChatHistoryQuery", () => {
  beforeEach(() => {
    mockedUsePaginatedList.mockReset();
  });

  it("maps session history messages without truncating loaded pages", () => {
    const items: SessionMessageItem[] = Array.from({ length: 520 }, (_, i) => {
      const minute = String(Math.floor(i / 60)).padStart(2, "0");
      const second = String(i % 60).padStart(2, "0");
      return {
        id: `msg-${i}`,
        role: i % 2 === 0 ? "assistant" : "user",
        content: `content-${i}`,
        created_at: `2026-02-12T00:${minute}:${second}.000Z`,
        metadata:
          i === 0
            ? {
                message_blocks: [
                  {
                    id: "blk-r",
                    type: "reasoning",
                    content: "reasoning-0",
                    is_finished: true,
                    created_at: "2026-02-12T00:00:00.100Z",
                    updated_at: "2026-02-12T00:00:00.200Z",
                  },
                  {
                    id: "blk-t",
                    type: "tool_call",
                    content: "tool-0",
                    is_finished: true,
                    created_at: "2026-02-12T00:00:00.300Z",
                    updated_at: "2026-02-12T00:00:00.400Z",
                  },
                ],
              }
            : undefined,
      };
    });

    mockedUsePaginatedList.mockReturnValue(createPaginatedResult(items));

    const { result } = renderHook(() =>
      useSessionHistoryQuery({
        conversationId: "conversation-1",
        enabled: true,
      }),
    );

    expect(result.current.messages).toHaveLength(items.length);
    expect(result.current.messages[0]).toMatchObject({
      id: "msg-0",
      role: "agent",
      content: "content-0",
      blocks: [
        expect.objectContaining({
          id: "blk-r",
          type: "reasoning",
          content: "reasoning-0",
        }),
        expect.objectContaining({
          id: "blk-t",
          type: "tool_call",
          content: "tool-0",
        }),
      ],
    });

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["history", "chat", "conversation-1"]);
    expect(options?.enabled).toBe(true);
    expect(options?.refetchOnWindowFocus).toBe(false);
    expect(options?.refetchOnReconnect).toBe(false);
    expect(options?.refetchOnMount).toBe(true);
    expect(options?.staleTime).toBe(0);
  });

  it("disables session history query when conversation id is missing", () => {
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

  it("pauses session history query while chat stream is active", () => {
    mockedUsePaginatedList.mockReturnValue(createPaginatedResult([]));

    renderHook(() =>
      useSessionHistoryQuery({
        conversationId: "conversation-1",
        enabled: true,
        paused: true,
      }),
    );

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.enabled).toBe(false);
  });
});
