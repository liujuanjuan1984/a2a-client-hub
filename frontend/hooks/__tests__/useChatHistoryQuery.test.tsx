import { renderHook } from "@testing-library/react-native";

import { useSessionHistoryQuery } from "@/hooks/useChatHistoryQuery";
import { usePaginatedList } from "@/hooks/usePaginatedList";
import { type ChatMessage } from "@/lib/api/chat-utils";
import { listSessionMessagesPage } from "@/lib/api/sessions";

jest.mock("@/hooks/usePaginatedList", () => ({
  usePaginatedList: jest.fn(),
}));

jest.mock("@/lib/api/sessions", () => ({
  listSessionMessagesPage: jest.fn(),
}));

jest.mock("@/lib/storage/mmkv", () => ({
  createPersistStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
}));

const mockedUsePaginatedList = jest.mocked(usePaginatedList);
const mockedListSessionMessagesPage = jest.mocked(listSessionMessagesPage);

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
    mockedListSessionMessagesPage.mockReset();
  });

  it("maps session history messages without truncating loaded pages", () => {
    const items: ChatMessage[] = Array.from({ length: 520 }, (_, i) => {
      const minute = String(Math.floor(i / 60)).padStart(2, "0");
      const second = String(i % 60).padStart(2, "0");
      const messageId = `msg-${i}`;
      return {
        id: messageId,
        role: i % 2 === 0 ? "agent" : "user",
        content: `content-${i}`,
        blocks: [
          {
            id: `${messageId}:block-1`,
            type: "text",
            content: `content-${i}`,
            isFinished: true,
            createdAt: `2026-02-12T00:${minute}:${second}.000Z`,
            updatedAt: `2026-02-12T00:${minute}:${second}.000Z`,
          },
        ],
        createdAt: `2026-02-12T00:${minute}:${second}.000Z`,
        status: "done",
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
          id: "msg-0:block-1",
          type: "text",
          content: "content-0",
        }),
      ],
    });

    const options = mockedUsePaginatedList.mock.calls[0]?.[0];
    expect(options?.queryKey).toEqual(["history", "chat", "conversation-1"]);
    expect(options?.enabled).toBe(true);
    expect(options?.refetchOnWindowFocus).toBe(true);
    expect(options?.refetchOnReconnect).toBe(true);
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

  it("loads timeline pages with before cursor chaining", async () => {
    let fetchPage: ((page: number) => Promise<{ nextPage?: number }>) | null =
      null;
    mockedUsePaginatedList.mockImplementation((options: any) => {
      fetchPage = options.fetchPage;
      return createPaginatedResult([]);
    });
    mockedListSessionMessagesPage
      .mockResolvedValueOnce({
        items: [
          {
            id: "msg-2",
            role: "agent",
            created_at: "2026-02-12T00:00:01.000Z",
            status: "done",
            blocks: [],
          },
        ],
        pageInfo: { hasMoreBefore: true, nextBefore: "cursor-1" },
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: "msg-1",
            role: "user",
            created_at: "2026-02-12T00:00:00.000Z",
            status: "done",
            blocks: [],
          },
        ],
        pageInfo: { hasMoreBefore: false, nextBefore: null },
      });

    renderHook(() =>
      useSessionHistoryQuery({
        conversationId: "conversation-1",
        enabled: true,
      }),
    );
    if (!fetchPage) {
      throw new Error("fetchPage is unavailable");
    }
    const runFetchPage = fetchPage as unknown as (page: number) => Promise<{
      nextPage?: number;
    }>;
    const firstResult = await runFetchPage(1);
    expect(mockedListSessionMessagesPage).toHaveBeenNthCalledWith(
      1,
      "conversation-1",
      {
        before: null,
        limit: 8,
      },
    );
    expect(firstResult.nextPage).toBe(2);

    const secondResult = await runFetchPage(2);
    expect(mockedListSessionMessagesPage).toHaveBeenNthCalledWith(
      2,
      "conversation-1",
      {
        before: "cursor-1",
        limit: 8,
      },
    );
    expect(secondResult.nextPage).toBeUndefined();
  });
});
