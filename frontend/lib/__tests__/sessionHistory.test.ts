import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("session history mapping", () => {
  it("hydrates agent blocks from metadata.message_blocks", () => {
    const mapped = mapSessionMessagesToChatMessages(
      [
        {
          id: "msg-1",
          role: "assistant",
          content: "final",
          created_at: "2026-02-14T00:00:00.000Z",
          metadata: {
            message_blocks: [
              {
                id: "blk-1",
                type: "reasoning",
                content: "thinking",
                is_finished: true,
                created_at: "2026-02-14T00:00:00.100Z",
                updated_at: "2026-02-14T00:00:00.200Z",
              },
              {
                id: "blk-2",
                type: "text",
                content: "final",
                is_finished: true,
                created_at: "2026-02-14T00:00:00.300Z",
                updated_at: "2026-02-14T00:00:00.400Z",
              },
            ],
          },
        },
      ],
      "session-1",
    );

    expect(mapped[0]?.blocks).toEqual([
      {
        id: "blk-1",
        type: "reasoning",
        content: "thinking",
        isFinished: true,
        createdAt: "2026-02-14T00:00:00.100Z",
        updatedAt: "2026-02-14T00:00:00.200Z",
      },
      {
        id: "blk-2",
        type: "text",
        content: "final",
        isFinished: true,
        createdAt: "2026-02-14T00:00:00.300Z",
        updatedAt: "2026-02-14T00:00:00.400Z",
      },
    ]);
  });

  it("falls back to one text block when metadata blocks are absent", () => {
    const mapped = mapSessionMessagesToChatMessages(
      [
        {
          id: "msg-2",
          role: "assistant",
          content: "final",
          created_at: "2026-02-14T00:00:01.000Z",
          metadata: {},
        },
      ],
      "session-2",
    );

    expect(mapped[0]?.blocks).toEqual([
      {
        id: "msg-2:text",
        type: "text",
        content: "final",
        isFinished: true,
        createdAt: "2026-02-14T00:00:01.000Z",
        updatedAt: "2026-02-14T00:00:01.000Z",
      },
    ]);
  });
});
