import { mergeChatMessagesByCanonicalId } from "@/lib/messageMerge";

describe("mergeChatMessagesByCanonicalId", () => {
  it("merges incoming messages by canonical id", () => {
    const merged = mergeChatMessagesByCanonicalId({
      current: [
        {
          id: "4aa4d7f3-68aa-41af-a366-76d9864f3eaa",
          role: "agent",
          content: "partial",
          createdAt: "2026-02-25T10:00:00.000Z",
          status: "done",
        },
      ],
      incoming: [
        {
          id: "4aa4d7f3-68aa-41af-a366-76d9864f3eaa",
          role: "agent",
          content: "final",
          createdAt: "2026-02-25T10:00:00.000Z",
          status: "done",
        },
      ],
      isActivelyStreaming: false,
    });

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      id: "4aa4d7f3-68aa-41af-a366-76d9864f3eaa",
      content: "final",
    });
  });

  it("keeps local streaming message when stream is active", () => {
    const merged = mergeChatMessagesByCanonicalId({
      current: [
        {
          id: "client-agent-2",
          role: "agent",
          content: "streaming",
          createdAt: "2026-02-25T10:01:00.000Z",
          status: "streaming",
        },
      ],
      incoming: [
        {
          id: "client-agent-2",
          role: "agent",
          content: "final-from-history",
          createdAt: "2026-02-25T10:01:00.000Z",
          status: "done",
        },
      ],
      isActivelyStreaming: true,
    });

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      id: "client-agent-2",
      content: "streaming",
      status: "streaming",
    });
  });
});
