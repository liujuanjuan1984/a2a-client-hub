import {
  getConversationMessages,
  mergeConversationMessages,
  setConversationMessages,
} from "@/lib/chatHistoryCache";
import { queryClient } from "@/services/queryClient";

describe("chatHistoryCache", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("stores conversation messages in query cache", () => {
    setConversationMessages("conv-1", [
      {
        id: "user-1",
        role: "user",
        content: "First question",
        createdAt: "2026-01-01T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
    ]);

    expect(
      queryClient.getQueryData(["history", "chat", "conv-1"]),
    ).toBeTruthy();
  });

  it("merges new messages without dropping existing history", () => {
    setConversationMessages("conv-1", [
      {
        id: "user-1",
        role: "user",
        content: "First question",
        createdAt: "2026-01-01T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
    ]);

    mergeConversationMessages("conv-1", [
      {
        id: "assistant-1",
        role: "agent",
        content: "First answer",
        createdAt: "2026-01-01T00:00:01.000Z",
        status: "done",
        blocks: [],
      },
    ]);

    expect(getConversationMessages("conv-1")).toEqual([
      {
        id: "user-1",
        role: "user",
        content: "First question",
        createdAt: "2026-01-01T00:00:00.000Z",
        status: "done",
        blocks: [],
      },
      {
        id: "assistant-1",
        role: "agent",
        content: "First answer",
        createdAt: "2026-01-01T00:00:01.000Z",
        status: "done",
        blocks: [],
      },
    ]);
  });
});
