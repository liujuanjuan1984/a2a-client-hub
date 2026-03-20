import { act, renderHook } from "@testing-library/react-native";

import { useChatBlockDetailController } from "@/hooks/useChatBlockDetailController";
import { querySessionMessageBlocks } from "@/lib/api/sessions";
import {
  getConversationMessages,
  updateConversationMessageWithUpdater,
} from "@/lib/chatHistoryCache";
import { toast } from "@/lib/toast";

jest.mock("@/lib/api/sessions", () => ({
  querySessionMessageBlocks: jest.fn(),
}));

jest.mock("@/lib/chatHistoryCache", () => ({
  getConversationMessages: jest.fn(),
  updateConversationMessageWithUpdater: jest.fn(),
}));

jest.mock("@/lib/toast", () => ({
  toast: {
    error: jest.fn(),
  },
}));

const mockedQuerySessionMessageBlocks =
  querySessionMessageBlocks as jest.MockedFunction<
    typeof querySessionMessageBlocks
  >;
const mockedGetConversationMessages =
  getConversationMessages as jest.MockedFunction<
    typeof getConversationMessages
  >;
const mockedUpdateConversationMessageWithUpdater =
  updateConversationMessageWithUpdater as jest.MockedFunction<
    typeof updateConversationMessageWithUpdater
  >;
const mockedToastError = toast.error as jest.MockedFunction<typeof toast.error>;

describe("useChatBlockDetailController", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("loads missing block details and applies them to the cached message", async () => {
    mockedGetConversationMessages.mockReturnValue([
      {
        id: "msg-1",
        role: "agent",
        createdAt: "2026-03-18T00:00:00.000Z",
        blocks: [
          {
            id: "block-1",
            type: "reasoning",
            content: [],
            isFinished: false,
          },
        ],
      },
    ] as never);
    mockedQuerySessionMessageBlocks.mockResolvedValue({
      items: [
        {
          id: "block-1",
          messageId: "msg-1",
          type: "reasoning",
          content: ["expanded detail"],
          isFinished: true,
        },
      ],
    } as never);

    const { result } = renderHook(() => useChatBlockDetailController("conv-1"));

    let ok = false;
    await act(async () => {
      ok = await result.current.handleLoadBlockContent("msg-1", "block-1");
    });

    expect(ok).toBe(true);
    expect(mockedQuerySessionMessageBlocks).toHaveBeenCalledWith("conv-1", {
      blockIds: ["block-1"],
    });
    expect(mockedUpdateConversationMessageWithUpdater).toHaveBeenCalledTimes(1);
    expect(mockedUpdateConversationMessageWithUpdater).toHaveBeenCalledWith(
      "conv-1",
      "msg-1",
      expect.any(Function),
    );
    expect(mockedToastError).not.toHaveBeenCalled();
  });

  it("deduplicates in-flight block detail requests", async () => {
    let resolveQuery:
      | ((value: {
          items: {
            id: string;
            messageId: string;
            type: string;
            content: string[];
            isFinished: boolean;
          }[];
        }) => void)
      | null = null;

    mockedGetConversationMessages.mockReturnValue([
      {
        id: "msg-1",
        role: "agent",
        createdAt: "2026-03-18T00:00:00.000Z",
        blocks: [
          {
            id: "block-1",
            type: "reasoning",
            content: [],
            isFinished: false,
          },
        ],
      },
    ] as never);
    mockedQuerySessionMessageBlocks.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveQuery = resolve;
        }) as never,
    );

    const { result } = renderHook(() => useChatBlockDetailController("conv-1"));

    let firstResult: Promise<boolean>;
    act(() => {
      firstResult = result.current.handleLoadBlockContent("msg-1", "block-1");
    });

    let secondResult = true;
    await act(async () => {
      secondResult = await result.current.handleLoadBlockContent(
        "msg-1",
        "block-1",
      );
    });

    expect(secondResult).toBe(false);
    expect(mockedQuerySessionMessageBlocks).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveQuery?.({
        items: [
          {
            id: "block-1",
            messageId: "msg-1",
            type: "reasoning",
            content: ["expanded detail"],
            isFinished: true,
          },
        ],
      });
      expect(await firstResult!).toBe(true);
    });
  });

  it("rejects block details that point to a different message", async () => {
    mockedGetConversationMessages.mockReturnValue([
      {
        id: "msg-1",
        role: "agent",
        createdAt: "2026-03-18T00:00:00.000Z",
        blocks: [
          {
            id: "block-1",
            type: "reasoning",
            content: [],
            isFinished: false,
          },
        ],
      },
    ] as never);
    mockedQuerySessionMessageBlocks.mockResolvedValue({
      items: [
        {
          id: "block-1",
          messageId: "msg-2",
          type: "reasoning",
          content: ["expanded detail"],
          isFinished: true,
        },
      ],
    } as never);

    const { result } = renderHook(() => useChatBlockDetailController("conv-1"));

    let ok = true;
    await act(async () => {
      ok = await result.current.handleLoadBlockContent("msg-1", "block-1");
    });

    expect(ok).toBe(false);
    expect(mockedUpdateConversationMessageWithUpdater).not.toHaveBeenCalled();
    expect(mockedToastError).toHaveBeenCalledWith(
      "Load block failed",
      "Block ownership mismatch.",
    );
  });

  it("reloads completed tool_call blocks when only raw content is cached", async () => {
    mockedGetConversationMessages.mockReturnValue([
      {
        id: "msg-tool-1",
        role: "agent",
        createdAt: "2026-03-18T00:00:00.000Z",
        blocks: [
          {
            id: "block-tool-1",
            type: "tool_call",
            content:
              '{"call_id":"call-1","tool":"bash","status":"completed","output":"done"}',
            isFinished: true,
            toolCall: {
              name: "bash",
              status: "success",
              callId: "call-1",
              result: "done",
            },
          },
        ],
      },
    ] as never);
    mockedQuerySessionMessageBlocks.mockResolvedValue({
      items: [
        {
          id: "block-tool-1",
          messageId: "msg-tool-1",
          type: "tool_call",
          content:
            '{"call_id":"call-1","tool":"bash","status":"completed","output":"done"}',
          isFinished: true,
          toolCall: {
            name: "bash",
            status: "success",
            callId: "call-1",
            result: "done",
          },
          toolCallDetail: {
            name: "bash",
            status: "success",
            callId: "call-1",
            timeline: [{ status: "completed", output: "done" }],
            raw: '{"call_id":"call-1","tool":"bash","status":"completed","output":"done"}',
          },
        },
      ],
    } as never);

    const { result } = renderHook(() => useChatBlockDetailController("conv-1"));

    let ok = false;
    await act(async () => {
      ok = await result.current.handleLoadBlockContent(
        "msg-tool-1",
        "block-tool-1",
      );
    });

    expect(ok).toBe(true);
    expect(mockedQuerySessionMessageBlocks).toHaveBeenCalledWith("conv-1", {
      blockIds: ["block-tool-1"],
    });
    expect(mockedUpdateConversationMessageWithUpdater).toHaveBeenCalledTimes(1);
  });

  it("skips reloading completed tool_call blocks when structured detail is already cached", async () => {
    mockedGetConversationMessages.mockReturnValue([
      {
        id: "msg-tool-2",
        role: "agent",
        createdAt: "2026-03-18T00:00:00.000Z",
        blocks: [
          {
            id: "block-tool-2",
            type: "tool_call",
            content:
              '{"call_id":"call-2","tool":"bash","status":"completed","output":"done"}',
            isFinished: true,
            toolCall: {
              name: "bash",
              status: "success",
              callId: "call-2",
              result: "done",
            },
            toolCallDetail: {
              name: "bash",
              status: "success",
              callId: "call-2",
              timeline: [{ status: "completed", output: "done" }],
            },
          },
        ],
      },
    ] as never);

    const { result } = renderHook(() => useChatBlockDetailController("conv-1"));

    let ok = false;
    await act(async () => {
      ok = await result.current.handleLoadBlockContent(
        "msg-tool-2",
        "block-tool-2",
      );
    });

    expect(ok).toBe(true);
    expect(mockedQuerySessionMessageBlocks).not.toHaveBeenCalled();
    expect(mockedUpdateConversationMessageWithUpdater).not.toHaveBeenCalled();
  });
});
