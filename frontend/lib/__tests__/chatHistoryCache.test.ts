import {
  getConversationTitleMap,
  setConversationMessages,
} from "@/lib/chatHistoryCache";
import { queryClient } from "@/services/queryClient";

describe("chatHistoryCache title map", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("returns first user message title for requested conversations", () => {
    setConversationMessages("conv-1", [
      {
        id: "agent-1",
        role: "agent",
        content: "assistant",
        createdAt: "2026-01-02T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
      {
        id: "user-2",
        role: "user",
        content: "   Second question   ",
        createdAt: "2026-01-03T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
      {
        id: "user-1",
        role: "user",
        content: "  First question  ",
        createdAt: "2026-01-01T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
    ]);
    setConversationMessages("conv-2", [
      {
        id: "agent-2",
        role: "agent",
        content: "assistant",
        createdAt: "2026-01-01T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
    ]);

    const titles = getConversationTitleMap(["conv-1", "conv-2", "missing"]);
    expect(titles).toEqual({
      "conv-1": "First question",
    });
  });
});
