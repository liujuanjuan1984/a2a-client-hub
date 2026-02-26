import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("session history mapping", () => {
  it("maps canonical ids from block-based history", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "1c7cf18e-4936-4de0-84f5-edf2e636ed41",
        role: "assistant",
        created_at: "2026-02-14T00:00:00.000Z",
        blocks: [
          {
            id: "block-1",
            seq: 1,
            type: "text",
            content: "final",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped[0]).toMatchObject({
      id: "1c7cf18e-4936-4de0-84f5-edf2e636ed41",
      role: "agent",
      content: "final",
    });
  });

  it("builds one text block for agent message content", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "2fbe098d-7af0-4bf9-8402-a1778aeeeb2f",
        role: "assistant",
        created_at: "2026-02-14T00:00:01.000Z",
        blocks: [
          {
            id: "block-2",
            seq: 1,
            type: "text",
            content: "final",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped[0]?.blocks).toEqual([
      {
        id: "block-2",
        type: "text",
        content: "final",
        isFinished: true,
        createdAt: "2026-02-14T00:00:01.000Z",
        updatedAt: "2026-02-14T00:00:01.000Z",
      },
    ]);
  });

  it("skips entries that do not provide block payload", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "3b9bdc78-93f3-4489-82e5-6967e35ecf36",
        role: "assistant",
        created_at: "2026-02-14T00:00:02.000Z",
      },
    ]);

    expect(mapped).toEqual([]);
  });

  it("skips entries when no blocks are present by default", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "4f08d8cb-93f5-4df5-b01c-383afbb2be26",
        role: "assistant",
        created_at: "2026-02-14T00:00:03.000Z",
      },
    ]);

    expect(mapped).toEqual([]);
  });

  it("maps streaming status from timeline payload", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "f9b8b086-15ce-4f14-84f4-b9861064da18",
        role: "assistant",
        created_at: "2026-02-14T00:00:03.500Z",
        status: "streaming",
        blocks: [
          {
            id: "block-3",
            seq: 1,
            type: "text",
            content: "partial",
            isFinished: false,
          },
        ],
      },
    ]);

    expect(mapped).toHaveLength(1);
    expect(mapped[0]).toMatchObject({
      id: "f9b8b086-15ce-4f14-84f4-b9861064da18",
      role: "agent",
      content: "partial",
      status: "streaming",
    });
  });

  it("keeps empty messages when keepEmptyMessages is enabled", () => {
    const mapped = mapSessionMessagesToChatMessages(
      [
        {
          id: "5f4d5d35-9099-49a0-8ce2-2cf56d79314d",
          role: "user",
          created_at: "2026-02-14T00:00:04.000Z",
        },
      ],
      { keepEmptyMessages: true },
    );

    expect(mapped).toHaveLength(1);
    expect(mapped[0]).toMatchObject({
      id: "5f4d5d35-9099-49a0-8ce2-2cf56d79314d",
      role: "user",
      content: "",
      blocks: [],
    });
  });

  it("keeps interrupted status from payload", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "918272f7-6ddf-4d6d-90d9-4ca1f9cfdb2b",
        role: "assistant",
        created_at: "2026-02-14T00:00:05.000Z",
        status: "interrupted",
        blocks: [
          {
            id: "block-4",
            seq: 1,
            type: "text",
            content: "partial",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped).toHaveLength(1);
    expect(mapped[0]?.status).toBe("interrupted");
  });

  it("keeps error status from payload", () => {
    const mapped = mapSessionMessagesToChatMessages([
      {
        id: "a18c58c4-a546-4dd6-b088-3687dcff7319",
        role: "assistant",
        created_at: "2026-02-14T00:00:06.000Z",
        status: "error",
        blocks: [
          {
            id: "block-5",
            seq: 1,
            type: "text",
            content: "failed",
            isFinished: true,
          },
        ],
      },
    ]);

    expect(mapped).toHaveLength(1);
    expect(mapped[0]?.status).toBe("error");
  });
});
