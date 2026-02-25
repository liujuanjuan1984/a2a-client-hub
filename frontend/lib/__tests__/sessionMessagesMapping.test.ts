import { mapSessionMessagesToChatMessages } from "@/lib/sessionHistory";

describe("mapSessionMessagesToChatMessages", () => {
  it("maps roles, preserves canonical ids, and sorts by created_at", () => {
    const result = mapSessionMessagesToChatMessages([
      {
        id: "m-1",
        role: "assistant",
        created_at: "2025-01-02T00:00:00.000Z",
        blocks: [
          {
            id: "m-1:b-1",
            messageId: "m-1",
            seq: 1,
            type: "text",
            content: "A",
            isFinished: true,
          },
        ],
      },
      {
        id: "m-2",
        role: "user",
        content: "U", // user content may still exist for non-unified or transitional sources
        created_at: "2025-01-01T00:00:00.000Z",
      },
      {
        id: "m-3",
        role: "unknown",
        content: "S",
        created_at: "2025-01-03T00:00:00.000Z",
      },
    ]);

    expect(result.map((m) => m.role)).toEqual(["user", "agent", "system"]);
    expect(result.map((m) => m.content)).toEqual(["U", "A", "S"]);
    expect(result[0].id).toBe("m-2");
    expect(result[1].id).toBe("m-1");
    expect(result[2].id).toBe("m-3");
  });
});
