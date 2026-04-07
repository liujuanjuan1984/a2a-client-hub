import { setConversationMessages } from "@/lib/chatHistoryCache";
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
});
