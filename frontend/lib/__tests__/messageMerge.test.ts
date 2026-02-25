import { mergeChatMessagesByCanonicalId } from "@/lib/messageMerge";

describe("mergeChatMessagesByCanonicalId", () => {
  it("rekeys alias-id history message into canonical local id", () => {
    const merged = mergeChatMessagesByCanonicalId({
      current: [
        {
          id: "client-agent-1",
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
          clientMessageId: "client-agent-1",
        },
      ],
      isActivelyStreaming: false,
    });

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      id: "4aa4d7f3-68aa-41af-a366-76d9864f3eaa",
      content: "final",
      clientMessageId: "client-agent-1",
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
          id: "1a57d6db-cf90-4e89-a373-d89d5787af2f",
          role: "agent",
          content: "final-from-history",
          createdAt: "2026-02-25T10:01:00.000Z",
          status: "done",
          clientMessageId: "client-agent-2",
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
